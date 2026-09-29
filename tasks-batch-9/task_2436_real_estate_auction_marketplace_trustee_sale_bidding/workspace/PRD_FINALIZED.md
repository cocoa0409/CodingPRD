# Trustee Auction Marketplace API — Product Requirements Document

## 1. Introduction

Distressed real estate reaches the market through two clocks that rarely agree. One is the statutory clock of the county: a foreclosure trustee notices a sale date, confirms it, postpones it — sometimes repeatedly — or cancels it outright when the borrower reinstates or a bankruptcy stay lands. The other is the commercial clock of the marketplace: an operations team assembles auction sessions, publishes lots with opening bids and confidential reserves, registers and vets bidders, takes deposits, and hammers property down to the highest qualifying bid. The Trustee Auction Marketplace API exists to keep those two clocks reconciled inside one system of record, so that a county postponement recorded by a trustee at eleven in the morning immediately suspends the right lots, re-ages the right deposit holds, and leaves the right assets relistable — without an operator being asked to remember which of a dozen downstream records still needs touching.

This document specifies that system for the engineering team building it. The API serves eight distinct kinds of participant — marketplace administrators, sellers (servicers, banks, government-sponsored enterprises and private owners), foreclosure trustees, title officers, compliance officers, auction operations staff, registered bidders, and unauthenticated public visitors — and each of them sees a deliberately narrow slice of the same asset. Sellers disclose occupancy and title condition; title officers overwrite those disclosures with verified findings; compliance officers decide who may bid; auction operations run the session but are forbidden from single-handedly hammering a lot down and then executing its purchase contract. Bidders see only what the platform has chosen to publish, including an eviction-risk tier derived from the disclosures rather than the disclosures' raw legal detail.

Money is the third axis. Every monetary amount in the system is an integer count of cents, and the platform's revenue arrives through a buyer premium whose rate depends non-linearly on price, occupancy and title condition; through a document fee whose discount tier is keyed on a provisional total that the final total may fall below; through a seller commission expressed in basis points; and, when a buyer walks away, through a forfeited deposit split with the seller. Because the same lot can be priced twice — provisionally at the hammer and finally at contract execution, after a title search has landed in between — the specification is explicit about which snapshot each calculation reads. Ambiguity here is not a stylistic problem; it is a settlement problem.

## 2. Global Specifications & System-Wide Principles

This section defines the contracts that hold for every endpoint: authentication, envelope shape, pagination, temporal semantics, versioning, rounding, and the order in which the server rejects bad requests.

### 2.1. Participants, Headers and Role-Based Access Control

Every request — including public catalogue reads and bidder self-registration — must carry two headers. `X-User-ID` identifies the acting principal, and `X-User-Role` declares the capacity in which that principal is acting. If either header is absent, or if `X-User-Role` is not one of the eight role names below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well formed but the declared role is not authorized for the operation being called, the rejection is `ERR_FORBIDDEN_ROLE` (HTTP 403).

The eight recognized roles are `PlatformAdmin`, `Seller`, `Trustee`, `TitleOfficer`, `ComplianceOfficer`, `AuctionOps`, `Bidder`, and `Anonymous`.

- `PlatformAdmin` is the marketplace operator. It onboards sellers, drives the logical clock, and may read everything.
- `Seller` is a servicer, bank, government-sponsored enterprise or private seller. It owns its own asset listings, files their disclosures, and relists them.
- `Trustee` is the foreclosure trustee for the county-sale leg: it notices statutory sales and confirms, postpones or cancels them.
- `TitleOfficer` is a title company officer whose only write capability is recording the outcome of a title search — the finding that gates contract execution.
- `ComplianceOfficer` owns know-your-customer and eligibility control: it records identity-verification decisions and creates and lifts eligibility exclusions.
- `AuctionOps` is auction operations: it schedules events, builds lots, revises reserves, opens and closes bidding, executes purchase contracts, records escrow closings and fallout, and issues second-chance offers.
- `Bidder` is a registered buyer: it funds deposits, places bids, and responds to second-chance offers.
- `Anonymous` is an unauthenticated public visitor. It may register itself as a bidder and read the public auction catalogue, including the title and eviction-risk disclosures published for each asset.

Two of these roles are **entity-backed**, meaning `X-User-ID` is not merely an audit token but a foreign key into the data:

- When `X-User-Role` is `Seller`, `X-User-ID` is the `id` of the acting `Seller` row. Ownership checks compare `X-User-ID` against the `seller_id` of the `AssetListing` being acted on — and, on asset intake, against the `seller_id` supplied in the request body. A mismatch is `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
- When `X-User-Role` is `Bidder`, `X-User-ID` is the `id` of the acting `Bidder` row. Funding a deposit requires `X-User-ID` to equal the bidder id addressed in the path; placing a bid requires it to equal the `bidder_id` in the request body; responding to a second-chance offer requires it to equal that offer's `offered_bidder_id`; and reading an eligibility assessment for another bidder is refused. Each of these mismatches is also `ERR_NOT_RESOURCE_OWNER`.

The remaining six roles — `PlatformAdmin`, `Trustee`, `TitleOfficer`, `ComplianceOfficer`, `AuctionOps`, and `Anonymous` — carry **opaque** identity: `X-User-ID` is an operator or visitor token that is not tied to any persisted entity and is never compared against any row's `id`. The server does record it where the specification says so — an `AuctionOps` operator's `X-User-ID` is written to `closed_by_user_id` when that operator closes a lot and to `executed_by_user_id` when a contract is executed — but it performs no ownership lookup on it. Those two recorded values drive the platform's segregation-of-duties rule: the operator who hammered a lot down may not be the operator who executes that lot's purchase contract, and an attempt to do both is `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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

Collection endpoints are paginated through two query parameters. `limit` caps the number of records returned; it defaults to 10 when omitted, may not be smaller than 1, and may not exceed 100. `offset` is the number of records to skip before the page begins; it defaults to 0 and may not be negative. A `limit` outside the permitted range, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless a specific endpoint states otherwise, every collection is ordered by `created_at` ascending, so that pagination over a growing collection remains stable for records already written.

List responses populate `limit`, `offset`, `total_count`, and `has_more` in the `meta` object, where `total_count` is the number of records matching the request's filters before pagination is applied and `has_more` indicates whether records remain beyond the current page.

### 2.4. Collection Reads, Filters and Computed Projections

Beyond pagination, each collection endpoint accepts a small set of exact-match filters, and filters combine conjunctively. The complete filter vocabulary is:

- `GET /sellers/{id}/asset-listings` accepts `listing_status`.
- `GET /asset-listings` accepts `seller_id`, `listing_status`, and `county_code`.
- `GET /asset-listings/{id}/trustee-sales` accepts `status`.
- `GET /trustee-sales/{id}/auction-events` accepts `event_status`.
- `GET /auction-events` accepts `county_code` and `event_status`.
- `GET /auction-lots` accepts `auction_event_id`, `asset_listing_id`, and `lot_status`.
- `GET /auction-lots/{id}/sale-contracts` accepts `contract_status`.
- `GET /bidders/{id}/eligibility-exclusions` accepts `status` and `exclusion_type`.
- `GET /bids` accepts `auction_lot_id`, `bidder_id`, and `bid_status`.
- `GET /deposit-holds` accepts `bidder_id`, `auction_lot_id`, and `status`.
- `GET /second-chance-offers` accepts `auction_lot_id`, `offered_bidder_id`, and `status`.

These filtered collections matter more than usual in this domain, because several records are created by cascades rather than by a client call. A deposit hold created as a side effect of a bid, a second-chance offer whose recipient the server selected, and a prior-fallout exclusion written by the barring cascade are all discoverable only by listing their collection and filtering it.

Two reads are **computed projections** rather than stored rows: they run a calculation at request time and mutate nothing. `GET /auction-lots/{id}/settlement-preview` projects the two buyer-premium variants side by side together with the settlement that would be posted, and `GET /bidders/{id}/eligibility-assessment` runs the bidder risk score in a requested mode. Their response shapes are specified with the business rules they project, in §3.7 and §3.4 respectively.

### 2.5. The Logical Clock

Nothing in this system reads wall-clock time. Every deadline, bidding window, hold expiry, effective date and `*_at` field is evaluated against a server-held **logical clock**, which an administrator sets by supplying a `to_iso8601` instant. Before any such call has been made, the logical clock reads exactly `2026-08-01T00:00:00Z`, and the server must never fall back to real time.

Setting the clock is inert with respect to data: no entity is mutated and no deferred transition fires merely because time moved. Consequences of the clock passing a threshold are realized lazily, when the next request touches the affected record — a second-chance offer, for instance, is only moved to `EXPIRED` when someone tries to respond to it after its `expires_at`.

### 2.6. Common Resource Properties and Versioning

Every persisted resource in the system — sellers, asset listings, trustee sales, auction events, auction lots, bidders, eligibility exclusions, deposit holds, bids, sale contracts and second-chance offers alike — carries the same four system-managed properties:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): the logical-clock instant at which the record was created, serialized as an ISO 8601 UTC timestamp with three fractional digits, for example `2026-08-01T00:00:00.000Z`.
- `updated_at` (string): the logical-clock instant of the most recent mutation of the record, in the same format.
- `version` (integer): a counter that starts at 1 on creation and increases by exactly 1 on every mutation of that record.

Every other timestamp-valued field the system stores on a resource — every `*_at` field, whether the server stamped it from the logical clock or the client supplied it in a request body, such as `disclosure_ack_at`, `sale_scheduled_at`, `starts_at`, `ends_at`, `opened_at`, `lot_window_start_at`, `lot_window_end_at`, `bid_close_at`, `closed_at`, `placed_at`, `expires_at`, `effective_at`, `lifted_at`, `identity_verified_at`, `execution_at`, `closing_deadline_at`, `responded_at` and `fallout_at` — is serialized in that same three-fractional-digit form, and reads `null` for as long as it is unset.

The rule that makes this system tractable to reason about is that **a computed field is a mutation like any other**. When a cascade releases a deposit hold, the affected bidder's `deposit_available_cents` is recomputed; that recomputation refreshes the bidder's `updated_at` and increments the bidder's `version`, even though no client asked to modify the bidder. The same holds for a seller whose `settled_net_cents` moves, an asset listing whose `eviction_risk_tier` is recomputed, an auction event whose `lot_count` changes, and a lot whose `current_high_bid_cents` or `bid_close_at` is rewritten. Each record touched in a cascade advances its own `version` independently.

### 2.7. Optimistic Concurrency Control on Event and Lot Writes

Exactly two write operations are guarded by optimistic concurrency control, and on both of them the version field is a required input rather than an optional courtesy.

Adding a lot to an auction event requires `expected_auction_event_version` in the request body, carrying the `version` of the `AuctionEvent` as the client last read it. If that value does not equal the event's current `version`, the request is rejected with `ERR_STALE_EVENT_VERSION` (HTTP 412). A second lot addition is perfectly legitimate on its own terms — an event holds many lots — which is precisely why the check is needed: the roster the client believes it is extending may already contain a lot whose asset or window changes the outcome, and the stale expected version is the only signal the server has that the client has not seen it.

Revising a lot's reserve price requires `expected_auction_lot_version` in the request body, carrying the `version` of the `AuctionLot` as the client last read it. A mismatch against the lot's current `version` is rejected with `ERR_STALE_LOT_VERSION` (HTTP 412). Re-setting a reserve is also legitimate in isolation — the new value simply supersedes the old one — so the version check is the platform's only defence against a writer that has not observed the reserve, or the standing high bid, that is already in place.

No other endpoint accepts a version field, and no other endpoint performs a version check. Where a version field is required, its absence is a malformed request under `ERR_INVALID_REQUEST`.

### 2.8. Money, Basis Points and Rounding Discipline

All monetary amounts are integer counts of cents. There are no fractional cents anywhere in a stored field or a response body, and no monetary value is ever serialized as a string.

Where a calculation multiplies an amount by a rate — a percentage, or a figure in basis points, where one basis point is one ten-thousandth — the product is converted back to whole cents by **rounding half up**: a result of exactly one half cent rounds away from zero to the next whole cent. Two disciplines about *when* that rounding happens are load-bearing and are stated again alongside the calculations that depend on them:

1. **Rounding is applied once per component, not once per total.** In the seller settlement the commission and the marketing recovery are each rounded to whole cents on their own and the rounded figures are then added. Adding the two basis-point rates together and rounding the combined product once is a different computation that can differ by a cent, and it is not what this platform does.
2. **Rounding is applied once per rate sum in the buyer premium.** There the tier rate, the occupancy surcharge and the title surcharge are summed into a single rate first, and the product of price and that combined rate is rounded exactly once.

Two conservation identities must hold exactly, for every input, with no drift. A bidder's deposit pool always satisfies: available deposit plus the total amount held plus the total amount forfeited equals the total amount funded — where released holds contribute to none of those three terms. And a posted settlement always satisfies: the seller's net plus the platform fee plus the buyer premium equals the settlement gross. The forfeiture split preserves the same discipline by assigning the rounding remainder to the platform bucket, so the seller's share and the platform's share always add back to exactly the forfeited amount.

### 2.9. Rejection Precedence: The Validation Ladder

Most requests in this system can fail several ways at once. To make the API deterministic, every check the server performs occupies a fixed rung on a single global ladder, the ladder is walked in ascending order, and **the first failing check decides the response**; no later check can mask an earlier one, and no earlier check is skipped because a later one would also fail. The ladder is grouped into bands: authentication, then existence, then ownership, then request shape, then entity state, then optimistic concurrency, then compliance and safety, then referential consistency, then temporal windows, then value constraints, and finally the fiscal check.

The rungs, in order:

1. `ERR_UNAUTHENTICATED` (401) — `X-User-Role` and `X-User-ID` are both present and `X-User-Role` names a recognized role. Applies to every endpoint.
2. `ERR_FORBIDDEN_ROLE` (403) — the acting role appears in the called endpoint's authorized-role list. Applies to every endpoint.
3. `ERR_SELLER_NOT_FOUND` (404) — a seller id in the path or body resolves to a `Seller`. Applies to `GET /sellers/{id}`, `GET /sellers/{id}/asset-listings`, and `POST /asset-listings`.
4. `ERR_ASSET_LISTING_NOT_FOUND` (404) — an asset listing id in the path or body resolves to an `AssetListing`. Applies to `GET /asset-listings/{id}`, `GET /asset-listings/{id}/trustee-sales`, `POST /asset-listings/{id}/disclosures`, `POST /asset-listings/{id}/title-clearance`, `POST /asset-listings/{id}/relist`, `POST /trustee-sales`, and `POST /auction-events/{id}/lots`.
5. `ERR_TRUSTEE_SALE_NOT_FOUND` (404) — a trustee sale id in the path or body resolves to a `TrusteeSale`. Applies to `GET /trustee-sales/{id}`, `GET /trustee-sales/{id}/auction-events`, `POST /trustee-sales/{id}/confirm`, `POST /trustee-sales/{id}/postpone`, `POST /trustee-sales/{id}/cancel`, and `POST /auction-events`.
6. `ERR_AUCTION_EVENT_NOT_FOUND` (404) — the auction event id in the path resolves to an `AuctionEvent`. Applies to `GET /auction-events/{id}`, `POST /auction-events/{id}/lots`, `POST /auction-events/{id}/open`, and `POST /auction-events/{id}/reschedule`.
7. `ERR_AUCTION_LOT_NOT_FOUND` (404) — the auction lot id resolves to an `AuctionLot`. Applies to `GET /auction-lots/{id}`, `GET /auction-lots/{id}/sale-contracts`, `GET /auction-lots/{id}/settlement-preview`, `PATCH /auction-lots/{id}/reserve-price`, `POST /auction-lots/{id}/bids`, `POST /auction-lots/{id}/close`, `POST /auction-lots/{id}/sale-contract`, and `POST /auction-lots/{id}/second-chance-offers`.
8. `ERR_BIDDER_NOT_FOUND` (404) — a bidder id in the path or body resolves to a `Bidder`. Applies to `GET /bidders/{id}`, `GET /bidders/{id}/eligibility-exclusions`, `GET /bidders/{id}/eligibility-assessment`, `POST /bidders/{id}/identity-verification`, `POST /bidders/{id}/deposits`, and `POST /eligibility-exclusions`.
9. `ERR_EXCLUSION_NOT_FOUND` (404) — the exclusion id in the path resolves to an `EligibilityExclusion`. Applies to `POST /eligibility-exclusions/{id}/lift`.
10. `ERR_SALE_CONTRACT_NOT_FOUND` (404) — the contract id in the path resolves to a `SaleContract`. Applies to `GET /sale-contracts/{id}`, `POST /sale-contracts/{id}/close`, and `POST /sale-contracts/{id}/fallout`.
11. `ERR_OFFER_NOT_FOUND` (404) — the offer id in the path resolves to a `SecondChanceOffer`. Applies to `GET /second-chance-offers/{id}` and `POST /second-chance-offers/{id}/respond`.
12. `ERR_BID_NOT_FOUND` (404) — the bid id in the path resolves to a `Bid`. Applies to `GET /bids/{id}`.
13. `ERR_NOT_RESOURCE_OWNER` (403) — the entity-backed ownership rules of §2.1 hold. Applies to `POST /asset-listings`, `POST /asset-listings/{id}/disclosures`, `POST /asset-listings/{id}/relist`, `POST /bidders/{id}/deposits`, `POST /auction-lots/{id}/bids`, `POST /second-chance-offers/{id}/respond`, and `GET /bidders/{id}/eligibility-assessment`.
14. `ERR_INVALID_REQUEST` (400) — the body conforms to the endpoint's input contract: required fields present, enumerated fields carrying a member of their declared set, integers inside their declared ranges, every amount in cents strictly greater than zero, datetimes valid ISO 8601 UTC, an end instant strictly after its start instant, `limit` between 1 and 100 inclusive, and `offset` not negative. Applies to every endpoint.
15. `ERR_DUPLICATE_LOT_NUMBER` (409) — no other lot of the same auction event already uses the submitted `lot_number`. Applies to `POST /auction-events/{id}/lots`.
16. `ERR_AUDIT_MODE_REQUIRES_LOT` (422) — an eligibility assessment requested in `AUDIT` mode supplies `auction_lot_id`, because the audit needs a reference instant. Applies to `GET /bidders/{id}/eligibility-assessment`.
17. `ERR_LISTING_NOT_IN_INTAKE` (409) — the listing's `listing_status` is `INTAKE`. Applies to `POST /asset-listings/{id}/disclosures`.
18. `ERR_TITLE_CLEARANCE_ALREADY_SET` (409) — the listing's `title_clearance_status` is `PENDING`. Applies to `POST /asset-listings/{id}/title-clearance`.
19. `ERR_LISTING_NOT_RELISTABLE` (409) — the listing's `listing_status` is either `RELIST_PENDING` or `UNSOLD`. Applies to `POST /asset-listings/{id}/relist`.
20. `ERR_LISTING_NOT_LISTABLE` (409) — the asset being added as a lot has `listing_status` of either `DISCLOSURE_READY` or `LISTED`. Applies to `POST /auction-events/{id}/lots`.
21. `ERR_TRUSTEE_SALE_NOT_ACTIONABLE` (409) — the sale's `status` admits the requested transition: `PENDING` or `POSTPONED` for a confirmation, `PENDING` or `CONFIRMED` for a postponement, and `PENDING`, `CONFIRMED` or `POSTPONED` for a cancellation. Applies to `POST /trustee-sales/{id}/confirm`, `POST /trustee-sales/{id}/postpone`, and `POST /trustee-sales/{id}/cancel`.
22. `ERR_EVENT_NOT_SCHEDULED` (409) — the event's `event_status` is `SCHEDULED`. Applies to `POST /auction-events/{id}/open` and `POST /auction-events/{id}/lots`.
23. `ERR_EVENT_NOT_POSTPONED` (409) — the event's `event_status` is `POSTPONED`. Applies to `POST /auction-events/{id}/reschedule`.
24. `ERR_EVENT_NOT_LIVE` (409) — the lot's parent event has `event_status` of `LIVE`. Applies to `POST /auction-lots/{id}/bids` and `POST /auction-lots/{id}/close`.
25. `ERR_EVENT_HAS_NO_LOTS` (409) — the event's `lot_count` is at least 1. Applies to `POST /auction-events/{id}/open`.
26. `ERR_LOT_NOT_OPEN` (409) — the lot's `lot_status` is either `OPEN` or `EXTENDED`. Applies to `POST /auction-lots/{id}/bids` and `POST /auction-lots/{id}/close`.
27. `ERR_LOT_NOT_CLOSED_SOLD` (409) — the lot's `lot_status` is `CLOSED_SOLD`. Applies to `POST /auction-lots/{id}/sale-contract` and `POST /auction-lots/{id}/second-chance-offers`.
28. `ERR_LOT_HAS_BIDS` (409) — the lot's `current_high_bid_cents` is zero, because a reserve may not be moved once a bid stands. Applies to `PATCH /auction-lots/{id}/reserve-price`.
29. `ERR_BIDDER_NOT_REGISTERED` (409) — for an identity-verification decision, the bidder's `identity_verification_status` is `UNVERIFIED`; for bidding and for responding to an offer, the bidder's `registration_status` is anything other than `SUSPENDED`. This rung deliberately does not demand `REGISTERED`, so that a `PENDING_REVIEW` or `REJECTED` bidder is caught one band lower by rung 34 and a `BARRED` bidder by rung 35, keeping all three errors reachable. Applies to `POST /bidders/{id}/identity-verification`, `POST /auction-lots/{id}/bids`, and `POST /second-chance-offers/{id}/respond`.
30. `ERR_CONTRACT_NOT_EXECUTED` (409) — the contract's `contract_status` is `EXECUTED`. Applies to `POST /sale-contracts/{id}/close` and `POST /sale-contracts/{id}/fallout`.
31. `ERR_OFFER_NOT_OUTSTANDING` (409) — the offer's `status` is `OUTSTANDING`. Applies to `POST /second-chance-offers/{id}/respond`.
32. `ERR_STALE_EVENT_VERSION` (412) — `expected_auction_event_version` equals the event's current `version`. Applies to `POST /auction-events/{id}/lots`.
33. `ERR_STALE_LOT_VERSION` (412) — `expected_auction_lot_version` equals the lot's current `version`. Applies to `PATCH /auction-lots/{id}/reserve-price`.
34. `ERR_IDENTITY_UNVERIFIED` (409) — the bidder's `identity_verification_status` is `VERIFIED`. Applies to `POST /auction-lots/{id}/bids` and `POST /second-chance-offers/{id}/respond`.
35. `ERR_BIDDER_BARRED` (403) — the bidder's `registration_status` is anything other than `BARRED`. Applies to `POST /auction-lots/{id}/bids` and `POST /bidders/{id}/deposits`.
36. `ERR_BIDDER_EXCLUDED` (403) — no eligibility exclusion of this bidder is simultaneously `ACTIVE`, already effective at the logical clock, and scoped either platform-wide or to the county of the lot's auction event. Applies to `POST /auction-lots/{id}/bids` and `POST /second-chance-offers/{id}/respond`.
37. `ERR_SEGREGATION_OF_DUTIES` (403) — the acting `X-User-ID` differs from the lot's `closed_by_user_id`. Applies to `POST /auction-lots/{id}/sale-contract`.
38. `ERR_COUNTY_MISMATCH` (422) — the `county_code` in the body equals the referenced asset listing's `county_code`. Applies to `POST /trustee-sales`.
39. `ERR_TRUSTEE_SALE_NOT_CONFIRMED` (409) — the event either has no `trustee_sale_id` or its linked sale has `status` of `CONFIRMED`. Applies to `POST /auction-events/{id}/open`.
40. `ERR_TITLE_CLEARANCE_PENDING` (409) — the lot's asset has `title_clearance_status` of either `CLEARED` or `CLOUDED_DISCLOSED`. Applies to `POST /auction-lots/{id}/sale-contract`.
41. `ERR_TITLE_DEFECTIVE` (409) — the asset's `title_clearance_status` is not `DEFECTIVE`. Applies to `POST /auction-events/{id}/lots`, `POST /asset-listings/{id}/relist`, and `POST /auction-lots/{id}/sale-contract`.
42. `ERR_NO_BACKUP_BIDDER` (409) — the backup-bidder selection described in §3.8 yields at least one candidate. Applies to `POST /auction-lots/{id}/second-chance-offers`.
43. `ERR_DUPLICATE_ACTIVE_OFFER` (409) — no second-chance offer for this lot is already `OUTSTANDING`. Applies to `POST /auction-lots/{id}/second-chance-offers`.
44. `ERR_BID_WINDOW_CLOSED` (409) — the logical clock is strictly before the lot's `bid_close_at`. Applies to `POST /auction-lots/{id}/bids`.
45. `ERR_LOT_WINDOW_STILL_OPEN` (409) — the logical clock has reached or passed the lot's `bid_close_at`. Applies to `POST /auction-lots/{id}/close`.
46. `ERR_EVENT_NOT_STARTED` (409) — the logical clock has reached or passed the event's `starts_at`. Applies to `POST /auction-events/{id}/open`.
47. `ERR_COUNTY_SLOT_CONFLICT` (409) — the county-slot geometry of §2.12 finds no conflicting event. Applies to `POST /auction-events` and `POST /auction-events/{id}/reschedule`.
48. `ERR_LOT_WINDOW_CONFLICT` (409) — the lot-window geometry of §2.12 finds no conflicting lot for the same asset. Applies to `POST /auction-events/{id}/lots` and `POST /auction-events/{id}/reschedule`.
49. `ERR_LOT_WINDOW_OUTSIDE_EVENT` (422) — `lot_window_start_at` is at or after the event's `starts_at` and `lot_window_end_at` is at or before the event's `ends_at`. Applies to `POST /auction-events/{id}/lots`.
50. `ERR_SALE_DATE_NOT_FUTURE` (422) — the noticed sale instant is strictly after the logical clock: `sale_scheduled_at` on creation, `new_sale_at` on postponement, and the standing `sale_scheduled_at` on confirmation. Applies to `POST /trustee-sales`, `POST /trustee-sales/{id}/postpone`, and `POST /trustee-sales/{id}/confirm`.
51. `ERR_POSTPONEMENT_LIMIT_EXCEEDED` (409) — the `postponement_count` that would result from this postponement, that is the current count plus one, is at most `statutory_max_postponements`. Applies to `POST /trustee-sales/{id}/postpone`.
52. `ERR_CLOSING_DEADLINE_PASSED` (409) — the logical clock is at or before the contract's `closing_deadline_at`. Applies to `POST /sale-contracts/{id}/close`.
53. `ERR_OFFER_EXPIRED` (409) — the logical clock is at or before the offer's `expires_at`. When it is past, the offer is first moved to `EXPIRED` and only then is the request rejected. Applies to `POST /second-chance-offers/{id}/respond`.
54. `ERR_BID_BELOW_MINIMUM` (422) — the bid clears the lot's minimum, as defined in §3.5. Applies to `POST /auction-lots/{id}/bids`.
55. `ERR_RESERVE_BELOW_OPENING` (422) — `reserve_price_cents` is greater than or equal to `opening_bid_cents`. Applies to `POST /auction-events/{id}/lots` and `PATCH /auction-lots/{id}/reserve-price`.
56. `ERR_DEPOSIT_INSUFFICIENT` (402) — the bidder's `deposit_available_cents` is at least the lot's `required_deposit_cents`. This rung is skipped entirely when the bidder already holds a deposit hold on this lot whose `status` is `HELD` or `EXTENDED`. Applies to `POST /auction-lots/{id}/bids` and `POST /second-chance-offers/{id}/respond`.

### 2.10. Identifier Resolution Order

Where a request names more than one resource — one in the path and another in the body, or a chain of two path segments — identifiers are resolved strictly left to right, path before body, and the first identifier that fails to resolve determines the 404. Adding a lot to an event therefore resolves the asset listing named in the body before it resolves nothing else — the existence band of §2.9 places `ERR_ASSET_LISTING_NOT_FOUND` at rung 4 and `ERR_AUCTION_EVENT_NOT_FOUND` at rung 6, so a request naming a nonexistent asset under a nonexistent event answers with the asset error. Likewise, creating a trustee sale for an unknown asset answers `ERR_ASSET_LISTING_NOT_FOUND`, and scheduling an event against an unknown trustee sale answers `ERR_TRUSTEE_SALE_NOT_FOUND`, before any state or shape check runs.

### 2.11. Cascade Discipline Across the County-Sale Axis

The county sale is upstream of everything commercial. A `TrusteeSale` bridges an `AssetListing` to the `AuctionEvent`s noticed against it, each event carries lots, each lot carries deposit holds and bids, and each hold belongs to a bidder whose ledger must stay balanced. When the trustee moves the sale, the effect propagates down that chain **within the same request**, atomically, and each link is a named consequence of the link above it rather than an independent action a client could have taken:

- A **postponement** runs a five-link chain: the sale itself moves to `POSTPONED`; every auction event bound to it that is `SCHEDULED` or `LIVE` moves to `POSTPONED`; every lot of those events that is `OPEN` or `EXTENDED` moves to `SUSPENDED`; every deposit hold on those lots that is `HELD` or `EXTENDED` is re-aged under the hold-extension policy of §3.2; and every bidder touched by a hold change has their deposit ledger recomputed. A postponement is not a failed auction, so no asset listing changes `listing_status`: the asset stays `LISTED`.
- A **cancellation** runs the terminal variant: the sale moves to `CANCELLED`; every bound event that is `SCHEDULED`, `LIVE` or `POSTPONED` moves to `CANCELLED`; every non-terminal lot of those events moves to `WITHDRAWN`; every `ACTIVE` or `OUTBID` bid on those lots moves to `WITHDRAWN`; every `HELD` or `EXTENDED` hold on those lots is `RELEASED` with a `released_reason` of `EVENT_CANCELLED`; every affected bidder's ledger is recomputed; and every asset listing of those lots that was `LISTED` becomes `UNSOLD`, which makes it relistable.
- Conversely, effects bubble **upward** when a lot reaches a terminal status. Closing the last non-terminal lot of a `LIVE` event closes the event, and a lot sold under a `CONFIRMED` trustee sale marks that sale `HELD` — the county sale is thereby deemed conducted.

No client request is ever required, or accepted, to perform one of these downstream links on its own. Every record the chain touches independently refreshes its `updated_at` and increments its `version`, per §2.6.

### 2.12. Interval Arithmetic: County Slots and Lot Windows

The platform enforces two different exclusion rules over time intervals, and their arithmetic is deliberately not the same.

The **county slot** rule protects a county's calendar. The contended resource is the pair of a `county_code` and an event window running from `starts_at` to `ends_at`, widened symmetrically by a buffer of half an hour on each side — thirty minutes of settling time between sessions in the same jurisdiction. A candidate event conflicts with another event of the same county whose `event_status` is `SCHEDULED`, `LIVE` or `POSTPONED` when the candidate's start is at or before that other event's end plus the buffer **and** that other event's start is at or before the candidate's end plus the buffer. Both comparisons are inclusive, which makes the rule adjacency-hostile: a candidate starting exactly thirty minutes after another event's end still conflicts, and clearance requires a gap strictly greater than thirty minutes on whichever side is adjacent. Events that are `CANCELLED` or `CLOSED` never conflict, and an event never conflicts with itself — which matters when an event is rescheduled and re-checked against its own new window.

The **lot window** rule protects an asset from being auctioned twice at once. The contended resource is the pair of an `asset_listing_id` and a half-open window running from `lot_window_start_at` up to, but not including, `lot_window_end_at`. There is no buffer. A candidate lot conflicts with another lot of the same asset — across all events, not merely within one — whose `lot_status` is `PENDING`, `OPEN`, `EXTENDED` or `SUSPENDED` when the candidate's start is strictly before that lot's end **and** that lot's start is strictly before the candidate's end. Both comparisons are strict, making the rule adjacency-friendly: a candidate beginning at exactly the instant another lot's window ends does not conflict, so back-to-back windows for the same asset in two different events are legal. Lots that are `CLOSED_SOLD`, `CLOSED_NO_SALE` or `WITHDRAWN` never conflict.

Both geometries compare instants to the millisecond.

## 3. Business Logic & Workflows

The sections below follow the life of a distressed asset from intake to settlement, and then through the two ways a sale can come apart. Rules that belong to more than one stage are stated where they first bite and reinforced where they matter again.

### 3.1. Seller Onboarding, Asset Intake and the Two Disclosure Axes

Before any property can be auctioned, its counterparty must exist. A `PlatformAdmin` onboards each servicer, bank, government-sponsored enterprise or private owner as a seller of record, supplying the `org_name` (a non-blank legal name of between 1 and 200 characters), the `seller_type` — one of `SERVICER`, `BANK`, `PRIVATE_SELLER` or `GSE` — a `contact_email` for settlement correspondence, which must contain an at-sign, and the `settlement_account_ref`, an opaque banking reference the platform credits when a sale settles. The commission the platform will retain is agreed at onboarding as `default_commission_bps`, expressed in basis points between 0 and 1500 inclusive; when the field is omitted it is set to 500, which is five percent. A newly onboarded seller's `settled_net_cents` — the running total of net proceeds the platform has posted to it — starts at 0.

Asset intake is the seller's own act. The seller submits the subject property with its `seller_id`, `street_address`, `city`, `county_code` (an uppercase recording-jurisdiction code of between 3 and 32 characters, such as `CA-ALAMEDA`), the two-letter uppercase `state_code`, and `estimated_value_cents`, the seller's own estimate of fair market value in cents, which must be strictly greater than zero. Both the path-level ownership rule and the body's `seller_id` are checked against the acting `X-User-ID`, so a seller cannot file an asset under another seller's name.

A freshly intaken asset is deliberately incomplete. Its `listing_status` begins at `INTAKE` and its `title_clearance_status` at `PENDING`; `occupancy_status` and `title_condition` both begin at `UNKNOWN`; `relist_count` is 0 and `second_chance_eligible` is false; and `disclosure_ack_at` — the instant the seller acknowledged the disclosures — is not yet set. These two enumerations are the heart of the asset record, and it is worth naming their members up front: `occupancy_status` is one of `OWNER_OCCUPIED`, `TENANT_OCCUPIED`, `VACANT` or `UNKNOWN`, and `title_condition` is one of `CLEAR`, `JUNIOR_LIENS`, `CLOUDED` or `UNKNOWN`.

An asset listing runs **two independent lifecycles on one row**. The first is the marketplace axis, `listing_status`, whose members are `INTAKE`, `DISCLOSURE_READY`, `LISTED`, `SOLD_PENDING_CONTRACT`, `SOLD_CLOSED`, `UNSOLD` and `RELIST_PENDING`, with `SOLD_CLOSED` terminal. The second is the title-work axis, `title_clearance_status`, whose members are `PENDING`, `CLEARED`, `CLOUDED_DISCLOSED` and `DEFECTIVE`. Neither axis gates the other's transitions — a title search may complete before the asset is listed, while it is `LISTED`, or long after it has reached `SOLD_PENDING_CONTRACT` — and only cross-entity rules read both together.

Filing disclosures is what moves the marketplace axis off the starting line. The seller supplies the `occupancy_status` and `title_condition` observed on the ground; both values overwrite whatever the record held, `disclosure_ack_at` is stamped with the logical clock, the eviction risk tier is recomputed, and the listing advances `INTAKE → DISCLOSURE_READY`. Disclosures may be filed exactly once from `INTAKE`; a second attempt, or an attempt on an asset that has already moved on, is refused with `ERR_LISTING_NOT_IN_INTAKE`.

The disclosures are not published raw to bidders. What bidders see is `eviction_risk_tier`, one of `LOW`, `MEDIUM` or `HIGH`, derived from the two disclosure fields by a three-clause rule evaluated top to bottom, where **the first matching clause wins**:

1. If the `occupancy_status` is `TENANT_OCCUPIED`, or the `title_condition` is either `CLOUDED` or `UNKNOWN`, the tier is `HIGH`.
2. Otherwise, if the `occupancy_status` is `OWNER_OCCUPIED`, or the `title_condition` is `JUNIOR_LIENS`, the tier is `MEDIUM`.
3. Otherwise — which is to say, `occupancy_status` of `VACANT` or `UNKNOWN` together with a `title_condition` of `CLEAR` — the tier is `LOW`.

The precedence is what makes this rule sharp rather than merely suggestive. A tenant-occupied property with perfectly clear title is `HIGH`, because the eviction exposure dominates; an owner-occupied property with clouded title is also `HIGH`, because clause 1 matches before clause 2 is considered. An unknown occupancy on its own never forces `HIGH` — only the title axis does that. This calculation reads nothing but the single asset row being mutated, and its output is an enumerated value, so no rounding arises. Because a freshly intaken asset holds `UNKNOWN` on both axes, its tier is `HIGH` from the moment of intake.

Title work belongs to the `TitleOfficer` and to no one else. The officer records the search by supplying `clearance_outcome`, which names the axis-B state to move to and must be `CLEARED`, `CLOUDED_DISCLOSED` or `DEFECTIVE`; `verified_title_condition`, the officer's finding, which overwrites the seller's `title_condition` outright; and `title_report_reference`, the reference of the underlying report. Those last two are request inputs only: the officer's finding is recorded solely by overwriting `title_condition`, and neither `verified_title_condition` nor `title_report_reference` is carried on the asset listing as an attribute of its own or appears in the asset listing responses of §4. The title axis moves from `PENDING` to the outcome named, the eviction risk tier is recomputed against the verified condition, and the listing's `version` advances. Recording a title outcome also refreshes `provisional_buyer_premium_cents` on every lot of that asset that has not yet reached a terminal lot status, so the bidder-facing premium projection tracks the verified finding; a lot that has no hammer price yet holds a projection of 0. The title axis may be written only once per search cycle — the second attempt on a row that has left `PENDING` is `ERR_TITLE_CLEARANCE_ALREADY_SET`.

A finding of `DEFECTIVE` changes nothing on the marketplace axis by itself, and that is the point: the asset may still be sitting `LISTED` with live bids. What `DEFECTIVE` does is bar three separate operations for as long as it stands — adding the asset to an event as a lot, relisting it, and executing a purchase contract on it — each refused with `ERR_TITLE_DEFECTIVE`. The only escape is a fresh search cycle, which only a relist can open, and relisting is itself barred while the axis reads `DEFECTIVE`; a `DEFECTIVE` finding on a `SOLD_PENDING_CONTRACT` asset therefore strands that sale until the trustee or operations team unwinds it.

Relisting is the seller's reset. It takes an asset whose `listing_status` is `UNSOLD` or `RELIST_PENDING` back to `DISCLOSURE_READY`, increments `relist_count` by 1, resets `second_chance_eligible` to false, and resets `title_clearance_status` to `PENDING` so a fresh title search can run — the title axis loops with the marketplace axis rather than remaining pinned to a stale finding. It carries no request body. A relist attempted from any other `listing_status` is `ERR_LISTING_NOT_RELISTABLE`, one attempted by a seller that does not own the asset is `ERR_NOT_RESOURCE_OWNER`, and one attempted while the title axis reads `DEFECTIVE` is `ERR_TITLE_DEFECTIVE`.

### 3.2. The County Sale Leg: Notice, Confirmation, Postponement and Cancellation

The statutory sale is recorded by the `Trustee` against a specific asset. The notice carries the `asset_listing_id`, the `county_code` of the county holding the sale, the `sale_scheduled_at` instant currently noticed, and optionally `statutory_max_postponements`, the county's statutory cap on how many times this notice may be pushed, which must lie between 0 and 10 inclusive and is set to 3 when the field is omitted. The county on the notice must be the county of record on the asset: a mismatch between the submitted `county_code` and the asset's own is `ERR_COUNTY_MISMATCH`. A noticed sale must be in the future — a `sale_scheduled_at` that is not strictly after the logical clock is `ERR_SALE_DATE_NOT_FUTURE`. A new notice begins with `status` of `PENDING` and `postponement_count` of 0.

The county axis has five states — `PENDING`, `CONFIRMED`, `POSTPONED`, `CANCELLED` and `HELD` — of which `CANCELLED` and `HELD` are terminal, and it is genuinely cyclic: a sale may be confirmed, postponed, re-confirmed against its new date, postponed again, and so on until the statutory cap is reached.

Confirmation is the trustee's statement that the sale will proceed on the date now noticed. It accepts a `confirmation_reference`, the trustee's docket reference, which is stored on the record, and it is permitted from `PENDING` or from `POSTPONED` — the latter being the re-confirmation that closes the postponement loop, moving `POSTPONED → CONFIRMED`. Confirmation from any other status is `ERR_TRUSTEE_SALE_NOT_ACTIONABLE`, and confirmation of a sale whose standing `sale_scheduled_at` has already passed the logical clock is `ERR_SALE_DATE_NOT_FUTURE`. Confirmation matters commercially because an auction event bound to a county sale cannot be taken live until that sale is `CONFIRMED`.

Postponement is where the county's clock collides with the marketplace's. The trustee supplies `new_sale_at`, the newly noticed instant, and `postponement_reason`, the statutory or practical reason. The sale moves to `POSTPONED` from either `PENDING` or `CONFIRMED`, `postponement_count` rises by 1, and `sale_scheduled_at` is replaced by `new_sale_at`. Two guards apply before anything moves: the resulting count — the current `postponement_count` plus one — may not exceed `statutory_max_postponements`, or the request is `ERR_POSTPONEMENT_LIMIT_EXCEEDED`; and `new_sale_at` must be strictly after the logical clock, or the request is `ERR_SALE_DATE_NOT_FUTURE`. Postponements are not free to the buyer: each one recorded against the sale adds a carry charge to the eventual contract price, as §3.7 sets out.

The postponement then propagates, in the same request, down the chain described in §2.11. Every auction event bound to this sale whose `event_status` is `SCHEDULED` or `LIVE` becomes `POSTPONED`; a `SCHEDULED` event's lots simply stay `PENDING`, while a `LIVE` event's lots that are `OPEN` or `EXTENDED` become `SUSPENDED`. Each lot that suspends carries its deposit holds with it, and each affected asset stays `LISTED` — a postponement is a delay, not a failed auction.

**Re-aging a deposit hold** is the delicate link in that chain. For every hold on a suspending lot whose `status` is `HELD` or `EXTENDED`, the hold's own `extension_count` is first incremented by 1. If the incremented value is at most 2 — the platform grants a hold no more than two postponement-driven extensions — the hold becomes `EXTENDED` and its `expires_at` is rewritten to the logical clock advanced by thirty days. If the incremented value exceeds 2, the platform will not hold the bidder's money any longer: the hold becomes `RELEASED` with a `released_reason` of `EXTENSION_LIMIT`, and every bid that bidder holds on that lot whose `bid_status` is `ACTIVE` or `OUTBID` becomes `WITHDRAWN`, since the bid can no longer be backed by a deposit. Either branch changes what the bidder has encumbered, so as the fifth and final link every affected bidder's deposit ledger is recomputed by the rule in §3.4.

Cancellation is the terminal branch. The trustee supplies a `cancellation_reason` — a reinstatement, a bankruptcy stay, a rescinded notice — and the sale moves to `CANCELLED` from `PENDING`, `CONFIRMED` or `POSTPONED`. The cascade is the one spelled out in §2.11: bound events in `SCHEDULED`, `LIVE` or `POSTPONED` become `CANCELLED`; their non-terminal lots become `WITHDRAWN`; the `ACTIVE` and `OUTBID` bids on those lots become `WITHDRAWN`; the `HELD` and `EXTENDED` holds on those lots become `RELEASED` with a `released_reason` of `EVENT_CANCELLED`; every affected bidder's ledger is recomputed; and every asset that was `LISTED` on one of those lots becomes `UNSOLD`, ready to be relisted. Attempting to cancel a sale that is already `CANCELLED` or has reached `HELD` is `ERR_TRUSTEE_SALE_NOT_ACTIONABLE`.

The county axis has one transition no client can request. When a lot bound to a `CONFIRMED` sale is hammered down sold, that sale moves `CONFIRMED → HELD` as a system bubble-up: the statutory sale is deemed to have been conducted, and the notice is spent.

### 3.3. Building the Auction Calendar: Events, Lots and Reserves

`AuctionOps` composes the marketplace's calendar. An auction event is created with a `title` naming the session, the `county_code` whose calendar it occupies, and the window `starts_at` to `ends_at`, where the end must be strictly after the start. Binding to the county leg is optional: `trustee_sale_id` may be supplied to tie the session to a statutory sale, or omitted entirely, in which case the event is a pure real-estate-owned online session with no county linkage — and, as §3.7 explains, with no postponement carry in its pricing. A new event begins `SCHEDULED` with `reschedule_count` of 0 and `lot_count` of 0, and its window is checked against the county-slot geometry of §2.12; a collision is `ERR_COUNTY_SLOT_CONFLICT`. The event axis runs `SCHEDULED`, `LIVE`, `POSTPONED`, `CANCELLED` and `CLOSED`, with the last two terminal, and it cycles `SCHEDULED → LIVE → POSTPONED → SCHEDULED → LIVE` across county postponements.

Adding an asset to a `SCHEDULED` event creates an **auction lot**, the junction where the marketplace axis and the county axis finally meet. The operator supplies the `asset_listing_id` of the asset being offered; the `lot_number`, an operator-assigned ordinal that must be strictly greater than zero and must not already be in use by another lot of the same event, on pain of `ERR_DUPLICATE_LOT_NUMBER`; the bidding window `lot_window_start_at` and `lot_window_end_at`, where the end is strictly after the start; the `opening_bid_cents`, the minimum acceptable first bid, strictly greater than zero; the `reserve_price_cents`, the seller's confidential reserve, which must be greater than or equal to `opening_bid_cents` or the request is `ERR_RESERVE_BELOW_OPENING`; the `expected_auction_event_version` demanded by §2.7; and optionally `min_increment_cents`, the minimum raise over the standing high bid for any bid after the first, which must be strictly greater than zero and is set to 500000 cents — five thousand dollars — when omitted.

The lot's window must sit entirely inside its event's window: `lot_window_start_at` at or after the event's `starts_at` and `lot_window_end_at` at or before the event's `ends_at`, or the request is `ERR_LOT_WINDOW_OUTSIDE_EVENT`. It must also clear the lot-window geometry of §2.12 against every other non-terminal lot of the same asset in any event, or the request is `ERR_LOT_WINDOW_CONFLICT`. The asset itself must be listable — `listing_status` of `DISCLOSURE_READY` or `LISTED`, otherwise `ERR_LISTING_NOT_LISTABLE` — and its title axis must not read `DEFECTIVE`, otherwise `ERR_TITLE_DEFECTIVE`. The event must still be `SCHEDULED`: lots cannot be added to a session that has already gone live, which is `ERR_EVENT_NOT_SCHEDULED`.

A created lot begins `PENDING` with `extension_count`, `current_high_bid_cents`, `hammer_price_cents` and `provisional_buyer_premium_cents` all at 0, and with `bid_close_at` — the effective close instant that late bidding can push forward — initialised to `lot_window_end_at`. Creating the lot pulls its asset onto the marketplace: `listing_status` advances `DISCLOSURE_READY → LISTED`, and the step is idempotent for an asset already `LISTED` through another lot. The parent event's `lot_count` is recomputed to the number of lots now bound to it, and the event's `version` advances by 1 — which is exactly why the next lot addition must present a fresh `expected_auction_event_version`.

**The deposit a bidder must post is fixed once, at lot creation, and never retro-adjusted.** It is computed in two steps. First a base is taken as the larger of a floor of 500000 cents — five thousand dollars — and five percent of `opening_bid_cents` rounded half up to whole cents. Then that base is multiplied by an occupancy multiplier read from the asset's `occupancy_status` as it stands at the moment of lot creation, and the product is rounded half up to whole cents to give `required_deposit_cents`. The multiplier is 1.50 for `OWNER_OCCUPIED`, 1.25 for `TENANT_OCCUPIED`, 1.00 for `VACANT`, and 1.50 for `UNKNOWN` — an unknown occupancy is priced as conservatively as an owner-occupied one, because the platform cannot rule out an eviction. A later disclosure filing or title finding that changes the asset does not reprice a lot that already exists.

Reserves can be revised, but only on a virgin lot. An `AuctionOps` operator may rewrite `reserve_price_cents` while presenting the `expected_auction_lot_version` required by §2.7; the new reserve must still be at or above `opening_bid_cents`, or the request is `ERR_RESERVE_BELOW_OPENING`. The moment a bid stands on the lot — that is, as soon as `current_high_bid_cents` is anything other than 0 — the reserve is frozen, and a revision attempt is `ERR_LOT_HAS_BIDS`. A successful revision advances the lot's `version` by 1.

Taking a session live is a single operator action with no request body, and it is fenced by four conditions. The event must be `SCHEDULED`, or `ERR_EVENT_NOT_SCHEDULED`; it must hold at least one lot, so a `lot_count` of 0 is `ERR_EVENT_HAS_NO_LOTS`; the logical clock must have reached or passed the event's `starts_at`, or `ERR_EVENT_NOT_STARTED`; and if the event carries a `trustee_sale_id`, that sale's `status` must be `CONFIRMED`, or `ERR_TRUSTEE_SALE_NOT_CONFIRMED` — an event with no county linkage passes this gate unconditionally. The event then moves `SCHEDULED → LIVE`, `opened_at` is stamped with the logical clock, and every lot of the event whose `lot_status` is `PENDING` or `SUSPENDED` moves to `OPEN`. Note the second of those two source states: the same action that opens a fresh session is also the action that resumes one whose lots were suspended by a county postponement, so no separate un-suspend operation exists. Opening a lot has no monetary effect, since `required_deposit_cents` was fixed when the lot was created.

Rescheduling is how a postponed session returns to the calendar. The operator supplies `new_starts_at` and `new_ends_at`; the event must be `POSTPONED`, or `ERR_EVENT_NOT_POSTPONED`, and the new start must be strictly after the logical clock with the new end strictly after the new start, or the request is `ERR_INVALID_REQUEST`. The new window is re-checked against the county-slot geometry with the event itself excluded from consideration — an event never conflicts with its own old window — and a collision is `ERR_COUNTY_SLOT_CONFLICT`. On success the event moves `POSTPONED → SCHEDULED`, `starts_at` and `ends_at` are replaced by the submitted values, and `reschedule_count` rises by 1.

Every non-terminal lot of the rescheduled event — those whose `lot_status` is `PENDING` or `SUSPENDED` — travels with the event: `lot_window_start_at` and `lot_window_end_at` are both shifted by exactly the offset between the new start and the old start, `bid_close_at` is reset to the shifted `lot_window_end_at`, and `extension_count` is reset to 0, so a lot that had already consumed its late-bid extensions gets them back for the new session. The shifted windows are re-checked against the lot-window geometry, and a collision is `ERR_LOT_WINDOW_CONFLICT`. Suspended lots remain `SUSPENDED` through the reschedule — they are returned to `OPEN` only when the operator takes the event live again — and the reschedule itself leaves every deposit hold exactly as the postponement cascade left it.

### 3.4. Who May Bid: Registration, Identity, Deposits and Exclusions

Anyone may put their name forward. Bidder self-registration is open to the `Anonymous` visitor and takes only a `legal_name` as it will be presented for identity verification, an `email` containing an at-sign, and a `mailing_address` of record. The new bidder starts with `identity_verification_status` of `UNVERIFIED` and `registration_status` of `PENDING_REVIEW`, with `deposit_funded_cents`, `deposit_forfeited_cents` and `fallout_count` all at 0, and with `screen_risk_score` computed immediately — which for an unverified bidder with no history evaluates to 25.

Two enumerations govern a bidder's standing, and they are not the same thing. `identity_verification_status` is the know-your-customer outcome and is one of `UNVERIFIED`, `VERIFIED` or `REJECTED`. `registration_status` is bidding eligibility and is one of `PENDING_REVIEW`, `REGISTERED`, `SUSPENDED`, `REJECTED` or `BARRED`, with `REJECTED` and `BARRED` terminal. The registration axis is cyclic in its middle: a bidder may be suspended by a compliance exclusion and reinstated when that exclusion is lifted, `REGISTERED → SUSPENDED → REGISTERED`, as many times as compliance requires.

A `ComplianceOfficer` records the verification decision, supplying `decision` — either `VERIFIED` or `REJECTED` — together with the `document_reference` of the evidence examined. The decision may be recorded only while `identity_verification_status` is `UNVERIFIED`; recording it twice is `ERR_BIDDER_NOT_REGISTERED`. A `VERIFIED` decision sets `identity_verification_status` to `VERIFIED`, stamps `identity_verified_at` with the logical clock, advances `registration_status` `PENDING_REVIEW → REGISTERED`, and recomputes `screen_risk_score`, from which the identity penalty now drops out. A `REJECTED` decision sets `identity_verification_status` to `REJECTED` and drives `registration_status` `PENDING_REVIEW → REJECTED`, which is terminal, and likewise recomputes `screen_risk_score`. Either decision advances the bidder's `version` by 1. The instant recorded in `identity_verified_at` is not merely an audit stamp: the retrospective variant of the risk assessment reads it in place of the current status, so a bidder verified after an event began audits as unverified for that event.

Deposits are funded by the bidder itself, one top-up at a time, with an `amount_cents` strictly greater than zero and a `funding_reference` for the incoming wire. Funding increases `deposit_funded_cents` by the amount, recomputes the deposit ledger and the screen score, and advances the bidder's `version` by 1. A bidder that has been barred may not fund at all — the attempt is `ERR_BIDDER_BARRED` — and a bidder may only fund its own wallet, on pain of `ERR_NOT_RESOURCE_OWNER`.

**The deposit ledger** is the platform's accounting of that wallet, and it is recomputed from scratch — never adjusted incrementally — on every mutation that creates, extends, releases or captures a deposit hold, and on every funding. For the bidder in question, the platform sums the `amount_cents` of every one of that bidder's deposit holds whose `status` is `HELD` or `EXTENDED` to give the held total, and separately sums the `amount_cents` of every hold whose `status` is `CAPTURED` to give the forfeited total. The forfeited total is written to `deposit_forfeited_cents`, and `deposit_available_cents` is the bidder's `deposit_funded_cents` less the held total less the forfeited total. Every hold in the bidder's history participates, regardless of which lot or event it belongs to and regardless of age; there is no time window. Holds whose `status` is `RELEASED` contribute to none of the three terms, which is what allows a released hold to return money to the available balance without any explicit credit. All three figures are exact integer cents with no rounding anywhere, and together they satisfy the conservation identity of §2.8.

Exclusions are how compliance keeps a bidder out. A `ComplianceOfficer` records one against a `bidder_id`, naming the `exclusion_type` — `SANCTIONS_LIST`, `TRUSTEE_AFFILIATE`, `STATE_INELIGIBLE` or `PRIOR_FALLOUT` — the `effective_at` instant from which it bites, which may be in the future, an optional `county_code` scope, and optional `notes` for the analyst's reasoning. The scope field is the subtle one: the literal value `ALL` means the exclusion is platform-wide, and any other value confines it to auction events held in that county. When `county_code` is omitted it is set to `ALL`. `PRIOR_FALLOUT` is reserved for the platform's own use — it is written only by the barring cascade of §3.8 — and an exclusion submitted through the compliance endpoint with that `exclusion_type` is refused as a malformed request with `ERR_INVALID_REQUEST`. A new exclusion is created with `status` of `ACTIVE`, the other member of that enumeration being `LIFTED`.

Recording an exclusion suspends the bidder only when the exclusion is both platform-wide and already in force: if its `county_code` is `ALL` and its `effective_at` is at or before the logical clock, a bidder whose `registration_status` is `REGISTERED` moves `REGISTERED → SUSPENDED`. A county-scoped exclusion, or a platform-wide one dated in the future, leaves `registration_status` untouched — it will still block bidding in the counties and at the times it covers, through the eligibility gate, but it is not a suspension. Either way the bidder's `screen_risk_score` is recomputed, since the exclusion count feeds it.

Lifting an exclusion takes an optional `notes` addendum, moves the exclusion `ACTIVE → LIFTED`, and stamps `lifted_at` with the logical clock. Reinstatement is conditional and is evaluated after the lift has been applied: a `SUSPENDED` bidder returns `SUSPENDED → REGISTERED` only when no remaining exclusion of that bidder is simultaneously `ACTIVE`, scoped `ALL`, and effective at or before the logical clock — and only when the bidder is not `BARRED`, since barring is terminal and no lift can undo it. The `screen_risk_score` is recomputed either way, and `lifted_at` is retained permanently because the retrospective assessment resurrects exclusions that were still in force at the moment being audited.

**The bidder risk score** is a weighted sum, capped, with a hard eligibility line. The platform starts at zero and adds 25 points if the identity penalty applies, 20 points for each counted exclusion, 15 points for each entry in the bidder's `fallout_count`, and 10 points if the deposit penalty applies. The running total is then capped at 100 — the cap is applied after all four components have been summed, never per component. A bidder is deemed eligible when the resulting score is strictly below 40, so a score of 39 is eligible and a score of 40 is not. The deposit penalty applies only when the assessment has been given a specific lot to reason about, and then only when the bidder's `deposit_available_cents` is strictly less than that lot's `required_deposit_cents`; with no lot in context the deposit penalty is never applied.

The score is computed in one of two **modes**, and the difference between them is entirely a question of which snapshot of the world is read.

- In `SCREEN` mode — the forward-looking gate, and the mode whose result is stored in `screen_risk_score` — the identity penalty applies when the bidder's current `identity_verification_status` is anything other than `VERIFIED`. The counted exclusions are those whose `status` is `ACTIVE` and whose scope is either `ALL` or, when a lot has been supplied, the `county_code` of that lot's auction event. Exclusions dated in the future, with an `effective_at` after the logical clock, **are** counted, because a screen is asking whether this bidder is safe to let in rather than whether they were excluded at some past instant. When the platform refreshes `screen_risk_score` as a side effect of a mutation there is no lot in context, so only `ALL`-scoped exclusions are counted and the deposit penalty is not applied.
- In `AUDIT` mode — the chronological post-auction reconstruction — a lot is mandatory, and that lot's auction event's `starts_at` becomes the reference instant. The identity penalty applies when `identity_verified_at` is unset, or when it is later than the reference instant. The counted exclusions are those whose `effective_at` is at or before the reference instant and whose scope is either `ALL` or the event's `county_code`, and which were either still `ACTIVE` or were `LIFTED` with a `lifted_at` later than the reference instant. Future-dated exclusions are therefore excluded and since-lifted exclusions are resurrected — the exact mirror image of the screen. The deposit penalty, by deliberate exception, uses the bidder's **current** `deposit_available_cents`, because the audit reconstructs eligibility, not the ledger.

The assessment is available as a computed read that mutates nothing. It accepts `mode`, which defaults to `SCREEN` when omitted, and `auction_lot_id`, which is optional in `SCREEN` mode and mandatory in `AUDIT` mode — requesting an audit without it is `ERR_AUDIT_MODE_REQUIRES_LOT`. A `PlatformAdmin` or `ComplianceOfficer` may assess any bidder; a `Bidder` may assess only itself. The projection returns `bidder_id`, the `mode` that was run, the resulting `risk_score`, the boolean `eligible`, the `counted_exclusion_count` that the mode's rules admitted, and the points each component actually contributed as `identity_penalty_applied`, `exclusion_penalty_applied`, `fallout_penalty_applied` and `deposit_penalty_applied`.

### 3.5. Live Bidding, Deposit Holds and the Late-Bid Extension

Bidding is the busiest operation in the platform and the one with the longest gauntlet. A `Bidder` places a bid on a lot by supplying its own `bidder_id` — which must match the acting `X-User-ID`, or the request is `ERR_NOT_RESOURCE_OWNER` — and the `amount_cents` offered. The lot's parent event must be `LIVE`, or `ERR_EVENT_NOT_LIVE`; the lot itself must be `OPEN` or `EXTENDED`, or `ERR_LOT_NOT_OPEN`; the bidder must not be `SUSPENDED`, or `ERR_BIDDER_NOT_REGISTERED`; the bidder's identity must be `VERIFIED`, or `ERR_IDENTITY_UNVERIFIED`; the bidder must not be `BARRED`, or `ERR_BIDDER_BARRED`; and no exclusion of that bidder may be `ACTIVE`, already effective at the logical clock, and scoped either `ALL` or to the county of the lot's event, or the request is `ERR_BIDDER_EXCLUDED`. The ordering of those five compliance checks is the one fixed in §2.9, so a suspended bidder whose identity is also unverified is told `ERR_BIDDER_NOT_REGISTERED`.

Two window-and-money gates follow. The logical clock must still be strictly before the lot's `bid_close_at`; once it has reached or passed that instant the lot is shut to new bids and the attempt is `ERR_BID_WINDOW_CLOSED`. The amount must clear the lot's minimum: on a lot with no standing bid, where `current_high_bid_cents` is 0, the bid must be at least `opening_bid_cents`; on a lot that already has a standing bid, the bid must be at least `current_high_bid_cents` plus `min_increment_cents`. Anything less is `ERR_BID_BELOW_MINIMUM`. Finally the bidder's `deposit_available_cents` must be at least the lot's `required_deposit_cents`, or the bid is refused with `ERR_DEPOSIT_INSUFFICIENT` — unless the bidder already holds a deposit hold on this very lot whose `status` is `HELD` or `EXTENDED`, in which case the funding check is skipped entirely and the bidder may raise their own bid without posting a second deposit.

Acceptance rewrites the lot's competitive state in one atomic step. The bid that was standing — the one bid on the lot whose `bid_status` is `ACTIVE` — becomes `OUTBID`, and that displaced bidder's deposit hold on the lot is `RELEASED` with a `released_reason` of `OUTBID`, returning their money to their available balance immediately rather than at the end of the session. The new bid is written with a `bid_status` of `ACTIVE` and a `placed_at` stamped from the logical clock. Its `is_above_reserve` flag is fixed at acceptance as whether the `amount_cents` is greater than or equal to the lot's `reserve_price_cents`, and it is never revisited afterwards, even if the reserve is somehow different later. A deposit hold of exactly `required_deposit_cents` is created for the incoming bidder with a `status` of `HELD`, unless that bidder already holds a live hold on this lot, in which case the existing hold is left in place and reused. Both bidders' deposit ledgers are then recomputed, the lot's `current_high_bid_cents` is set to the accepted `amount_cents`, and the lot's `version` advances by 1. The four members of the bid standing enumeration are `ACTIVE`, `OUTBID`, `WINNING` and `WITHDRAWN`; a bid becomes `WINNING` only at lot close or through an accepted second-chance offer.

A deposit hold, then, is the encumbrance a bid rides on. It records the `bidder_id` whose money is held, the `auction_lot_id` it secures, the `amount_cents` snapshotted from the lot's `required_deposit_cents` at the moment of creation, a `status` from `HELD`, `EXTENDED`, `RELEASED` or `CAPTURED`, an `expires_at`, an `extension_count` counting the postponement-driven extensions applied to it, and — once it leaves the encumbered states — a `released_reason` from `OUTBID`, `NO_SALE`, `CONTRACT_CLOSED`, `EVENT_CANCELLED`, `EXTENSION_LIMIT` or `FORFEITED`. The `expires_at` is stamped at creation as the hold's creation instant advanced by the platform's initial hold period; the postponement cascade of §3.2 rewrites it to the logical clock plus thirty days, and contract execution rewrites it to the buyer's closing deadline.

**Late bidding extends the lot rather than punishing the late bidder.** After every validation has passed and immediately before the bid row is written, the platform measures the seconds remaining between the logical clock and the lot's `bid_close_at`, a quantity that may be fractional. If that remaining time is at most 60 seconds and the lot's `extension_count` is still strictly less than 3, the lot is extended: `bid_close_at` is rewritten to the logical clock advanced by 120 seconds, `extension_count` rises by 1, `lot_status` moves `OPEN → EXTENDED` (or stays `EXTENDED` on a self-loop when the lot was already extended), and the triggering bid records `triggered_extension` as true. Otherwise `bid_close_at` is left exactly where it was and the bid records `triggered_extension` as false. The boundary is inclusive on the trigger side and exclusive on the counter: with exactly 60 seconds remaining the lot extends, with 61 seconds remaining it does not, and once `extension_count` has reached 3 further late bids are still accepted — they simply no longer move the clock. A bid arriving with no time remaining at all never reaches this rule, because the closed-window gate has already rejected it.

### 3.6. Hammering Down: Lot Close, the Winner and the Provisional Premium

Closing a lot is an `AuctionOps` action with no request body, and it is the moment the marketplace commits. The lot must be `OPEN` or `EXTENDED` under a `LIVE` event, and the logical clock must have reached or passed the lot's `bid_close_at` — closing early, including closing before an extension that a late bid has just pushed out, is `ERR_LOT_WINDOW_STILL_OPEN`.

The winner is chosen by a narrow filter: the candidates are the bids on this lot whose `bid_status` is `ACTIVE` **and** whose `is_above_reserve` is true. Candidates rank by `amount_cents` descending, ties break in favour of the earlier `created_at`, and any remaining tie breaks in favour of the earlier `placed_at`. By construction at most one bid per lot is ever `ACTIVE`, since each acceptance demotes its predecessor to `OUTBID`, so this ranking chooses between zero rows and one. An empty candidate set is not an error: it is the no-sale outcome, and it arises both when nobody bid at all and when the standing bid never cleared the confidential reserve.

On a reserve-clearing winner the lot moves `OPEN → CLOSED_SOLD` or `EXTENDED → CLOSED_SOLD`. The winning bid's `bid_status` becomes `WINNING`; `hammer_price_cents` is fixed to that bid's `amount_cents`; `provisional_buyer_premium_cents` is computed under the provisional rule below; `closed_by_user_id` records the acting operator's `X-User-ID` and `closed_at` the logical clock. The asset moves `LISTED → SOLD_PENDING_CONTRACT` on its marketplace axis, and its `second_chance_eligible` flag is set from whether a qualifying backup pool exists for the lot, per §3.8. If the lot's event is bound to a trustee sale that is `CONFIRMED`, that sale moves `CONFIRMED → HELD`. No deposit holds are released by a sold close: the losing bidders' holds were already released the moment they were outbid, so the winner's hold is the only one still encumbered, and it is exactly the one the platform needs to keep. The lot's `version` advances by 1.

On an empty candidate set the lot moves `OPEN → CLOSED_NO_SALE` or `EXTENDED → CLOSED_NO_SALE`. Here `hammer_price_cents` stays 0 and `provisional_buyer_premium_cents` stays 0; a standing `ACTIVE` bid below reserve stays `ACTIVE`, since it never became a winner; every deposit hold on the lot whose `status` is `HELD` or `EXTENDED` is `RELEASED` with a `released_reason` of `NO_SALE`, and every affected bidder's deposit ledger is recomputed; and the asset moves `LISTED → UNSOLD`, which makes it relistable. `closed_by_user_id` and `closed_at` are recorded on this branch too, and the lot's `version` advances by 1.

Both branches bubble upward identically. If, after the closing lot has reached its terminal status, no lot of the parent event remains in `PENDING`, `OPEN`, `EXTENDED` or `SUSPENDED`, the event itself moves `LIVE → CLOSED`, which is terminal. The three terminal lot statuses are `CLOSED_SOLD`, `CLOSED_NO_SALE` and `WITHDRAWN`.

**The buyer premium** is the platform's fee to the buyer, and it is computed the same way in both of its variants; only its inputs differ. Three influences are combined into a single rate before any rounding happens. First a tier rate keyed on the price being premiumed: 0.10 when that price is strictly below 10000000 cents (one hundred thousand dollars), 0.08 when it is at least 10000000 cents but strictly below 50000000 cents (five hundred thousand dollars), and 0.06 at or above 50000000 cents. Second an occupancy surcharge read from the asset's `occupancy_status`, expressed in basis points: 150 for `OWNER_OCCUPIED`, 100 for `TENANT_OCCUPIED`, 0 for `VACANT`, and 200 for `UNKNOWN`. Third a title surcharge read from the asset's `title_condition`, also in basis points: 0 for `CLEAR`, 75 for `JUNIOR_LIENS`, 175 for `CLOUDED`, and 250 for `UNKNOWN`. Each surcharge is converted from basis points by dividing by ten thousand and added to the tier rate. The price is then multiplied by that single combined rate and the product is rounded half up to whole cents **exactly once**. The rounded figure is finally clamped: it is raised to a floor of 250000 cents (two thousand five hundred dollars) if it falls below that, and lowered to a ceiling of 6000000 cents (sixty thousand dollars) if it exceeds that.

The **provisional** variant runs at lot close and is written to the lot's `provisional_buyer_premium_cents`. Its price input is the lot's `hammer_price_cents`, with no postponement carry, and its `occupancy_status` and `title_condition` inputs are read exactly as they stand at the moment of the close request — which in practice usually means the title axis is still `PENDING` and the premium is therefore priced off the seller's own disclosure rather than a verified finding. The **final** variant runs at contract execution and is described in §3.7; it differs precisely in reading a different price and a re-read title condition, and the gap between the two is what the settlement preview exposes.

The settlement preview is available from lot close onward as a computed read for `PlatformAdmin`, `AuctionOps` and `Seller`; before a lot has closed every money field in it reads 0.

### 3.7. Contract Execution, Buyer Charges and Seller Settlement

Executing the purchase contract is the platform's single most consequential write, and it is guarded four ways. The lot must be `CLOSED_SOLD`, or the attempt is `ERR_LOT_NOT_CLOSED_SOLD`. The asset's title work must have landed: its `title_clearance_status` must be `CLEARED` or `CLOUDED_DISCLOSED`, so executing while the title axis is still `PENDING` is `ERR_TITLE_CLEARANCE_PENDING`, and executing against a `DEFECTIVE` finding is `ERR_TITLE_DEFECTIVE`. And the four-eyes rule of §2.1 applies: the acting `X-User-ID` must differ from the lot's `closed_by_user_id`, or the request is `ERR_SEGREGATION_OF_DUTIES` — the operator who hammered the lot down may not also be the operator who binds the buyer to it. The only input is the optional `closing_window_days`, the buyer's closing window in days measured from execution, which must lie between 1 and 90 inclusive and is set to 21 when omitted.

The contract identifies its lot by `auction_lot_id` and its buyer by `winning_bidder_id`, which the server resolves as the `bidder_id` of the bid on that lot whose `bid_status` is `WINNING` — exactly one such bid exists once the lot is `CLOSED_SOLD`. Execution stamps `execution_at` with the logical clock, records the acting operator as `executed_by_user_id`, sets `contract_status` to `EXECUTED`, and computes `closing_deadline_at` as `execution_at` advanced by `closing_window_days` days. The contract lifecycle enumerates `EXECUTED`, `CLOSED` and `FALLOUT`, with the latter two terminal, and it forks: one branch settles with the seller, the other forfeits the deposit and reopens the asset.

**Postponement carry.** The price the buyer signs for is not always the hammer price. If the lot's event carries no `trustee_sale_id`, the postponement count used for pricing is zero. Otherwise it is the linked trustee sale's `postponement_count` as it stands at the moment of the execution request. The carry is then the `hammer_price_cents` multiplied by 25 basis points and by that postponement count, all divided by ten thousand, with the result rounded half up to whole cents once over the whole expression — a quarter of one percent of the hammer for each time the county pushed the sale, charged to the buyer whose money was tied up through the delay. `contract_price_cents` is the `hammer_price_cents` plus that carry. Postponements recorded after execution never reprice an existing contract.

**The final buyer premium** runs the shared rule of §3.6 with two inputs changed. Its price input is `contract_price_cents`, hammer plus postponement carry, rather than the bare hammer — so a postponed sale can cross a premium tier boundary that the provisional run did not. And its `title_condition` input is re-read at execution time, after the title officer has overwritten the seller's disclosure with `verified_title_condition`, so the title surcharge in basis points may differ from the one the provisional run applied. The occupancy surcharge, the tier boundaries, the single half-up rounding of price times combined rate, and the floor and ceiling clamps are all identical to the provisional run. The result is stored as `final_buyer_premium_cents`.

**The document fee is a genuine circularity, broken by a pinned evaluation order.** The fee's discount depends on a tier keyed on the transaction total, and the total depends on the fee. The platform resolves this in exactly three steps and performs no fixed-point iteration. Step one computes a provisional total as `contract_price_cents` plus `final_buyer_premium_cents` plus the base document fee of 95000 cents (nine hundred and fifty dollars). Step two keys the discount on that provisional total: a discount of 0.40 when the provisional total is at least 50000000 cents, a discount of 0.25 when it is at least 25000000 cents but below that, and no discount otherwise; `doc_fee_cents` is then the base fee of 95000 cents multiplied by one minus the discount, rounded half up to whole cents. Step three computes `total_due_cents` as `contract_price_cents` plus `final_buyer_premium_cents` plus the discounted `doc_fee_cents`. A consequence to preserve rather than correct: `total_due_cents` may end up **below** the tier floor that granted its discount, because the tier is keyed on the step-one provisional total and is never re-keyed on the step-three result.

**The seller settlement** is posted in the same request, and its rounding order is the one warned about in §2.8. Three components are computed independently and each is rounded to whole cents on its own. The first is the seller's commission: `contract_price_cents` multiplied by the seller's `default_commission_bps`, divided by ten thousand, rounded half up. The second is the platform's marketing recovery: `contract_price_cents` multiplied by 35 basis points, divided by ten thousand, rounded half up. The third is a flat title service fee of 45000 cents (four hundred and fifty dollars), charged when and only when the asset's `title_condition` at execution time is anything other than `CLEAR`, and zero when it is `CLEAR`. `platform_fee_cents` is the exact integer sum of those three rounded components. `seller_net_cents` is `contract_price_cents` less `platform_fee_cents`. `buyer_premium_cents` on the contract records the premium the platform retains and equals `final_buyer_premium_cents`. `settlement_gross_cents` is `contract_price_cents` plus `final_buyer_premium_cents`, and the conservation identity of §2.8 — seller net plus platform fee plus buyer premium equalling the gross — must hold on every contract.

Posting the settlement moves the contract's second, independent axis. `settlement_status` enumerates `DRAFT`, `POSTED` and `VOID`; the settlement is posted in the execution request itself, so a freshly executed contract reads `POSTED`, and the seller's `settled_net_cents` rises by this contract's `seller_net_cents` at that moment. The winner's deposit hold is re-purposed rather than released: it becomes `EXTENDED` with its `expires_at` rewritten to the contract's `closing_deadline_at`, and — unlike the postponement path of §3.2 — its `extension_count` is **not** incremented, because it is the closing window and not the postponement policy that sets this expiry. Contract execution returns a newly created resource.

The **settlement preview** projects all of this without writing any of it, which is how a seller sees what the two premium variants did to their proceeds. It returns the `auction_lot_id` it was asked about, the `hammer_price_cents` and `contract_price_cents`, the `provisional_premium_cents` and `final_premium_cents` side by side, the `premium_variant_delta_cents` as the final premium less the provisional premium — a negative figure when a title search improved the recorded condition after the hammer fell — and the `doc_fee_cents`, `total_due_cents`, `settlement_gross_cents`, `seller_net_cents` and `platform_fee_cents` that would be posted.

Escrow closing is the happy ending. An `AuctionOps` operator records it with a `closing_reference` from escrow while the contract is still `EXECUTED` and the logical clock is at or before `closing_deadline_at`; closing late is `ERR_CLOSING_DEADLINE_PASSED`, and closing a contract that has already closed or fallen out is `ERR_CONTRACT_NOT_EXECUTED`. The contract moves `EXECUTED → CLOSED` with `closed_at` stamped from the logical clock. The buyer's deposit hold on the lot is `RELEASED` with a `released_reason` of `CONTRACT_CLOSED` and that bidder's deposit ledger is recomputed — the buyer's deposit comes back because the purchase money arrived through escrow instead. On the asset, `listing_status` completes its journey `SOLD_PENDING_CONTRACT → SOLD_CLOSED`, which is terminal on the marketplace axis. The settlement is already posted and is not re-posted: `settlement_status` stays `POSTED` and the seller's `settled_net_cents` is untouched by the closing.

### 3.8. When a Sale Falls Apart: Forfeiture, Barring and Second-Chance Offers

Buyers walk away. Recording fallout is an `AuctionOps` action on an `EXECUTED` contract, carrying only a `fallout_reason`, and it triggers the longest cascade in the platform. The contract moves `EXECUTED → FALLOUT` with `fallout_at` stamped from the logical clock. The settlement is unwound on the settlement axis alone: `settlement_status` moves `POSTED → VOID` and the seller's `settled_net_cents` is reduced by this contract's `seller_net_cents`, while the sale numbers themselves — `contract_price_cents`, `final_buyer_premium_cents`, `doc_fee_cents`, `total_due_cents`, `settlement_gross_cents`, `seller_net_cents`, `platform_fee_cents` and `buyer_premium_cents` — are all **retained unchanged** as the record of what was contracted.

The forfeiture follows as a direct consequence of that voiding. The winning bidder's deposit hold on the lot, whose `status` is `HELD` or `EXTENDED`, becomes `CAPTURED` with a `released_reason` of `FORFEITED`, and the contract's `forfeited_deposit_cents` is set to that hold's `amount_cents`. The bidder's `deposit_forfeited_cents` and `deposit_available_cents` are recomputed by the ledger rule of §3.4 — a captured hold, unlike a released one, permanently reduces the bidder's funded pool — and the bidder's `fallout_count` rises by 1.

The captured amount is then split. `forfeiture_seller_net_cents` is the `forfeited_deposit_cents` multiplied by 6000 basis points and divided by ten thousand — sixty percent — rounded half up to whole cents, and `forfeiture_platform_fee_cents` is whatever remains after subtracting the seller's share from the forfeited amount. Assigning the remainder rather than computing the platform's share independently is what makes the split exact for every input, with the two buckets always summing back to the forfeited deposit and no drift. The seller is credited for its share: `settled_net_cents` rises by `forfeiture_seller_net_cents`, having just been reduced by the voided `seller_net_cents`.

Finally the asset is queued to go round again: `listing_status` moves `SOLD_PENDING_CONTRACT → RELIST_PENDING`, and `second_chance_eligible` is recomputed against the backup pool described below. The lot's `hammer_price_cents` is deliberately retained, because it is the reference against which the second-chance economics are judged.

**Repeat defaulters are barred, not merely scored.** When the increment brings a bidder's `fallout_count` to 2 or more, that bidder's `registration_status` moves to `BARRED` — reachable from either `REGISTERED` or `SUSPENDED`, and terminal from both — and the platform writes an eligibility exclusion of its own accord, with an `exclusion_type` of `PRIOR_FALLOUT`, a `county_code` of `ALL`, an `effective_at` equal to the logical clock, and a `status` of `ACTIVE`. The bidder's `screen_risk_score` is recomputed, now carrying 15 points for each recorded fallout on top of any exclusion penalties. A barred bidder can neither bid nor fund further deposits, and because barring is terminal, lifting the auto-created exclusion later will not reinstate them.

**The backup bidder** is chosen by a filter deliberately different from the winning-bid filter. Candidates are the bids on the fallen-out lot whose `bid_status` is `OUTBID`, whose `amount_cents` is greater than or equal to the lot's `reserve_price_cents`, and whose bidder is currently both `REGISTERED` on the registration axis and `VERIFIED` on the identity axis. Bids that are `WITHDRAWN` or `WINNING` are excluded, and so is any bid below the reserve — the platform will not use a second chance to sell below the seller's floor. Candidates rank by `amount_cents` descending, ties break in favour of the earlier bid `created_at`, and any remaining tie breaks in favour of the earlier bidder `created_at`. Where one bidder holds several outbid bids on the lot, only that bidder's highest can ever rank first, so no bidder is offered the lot twice. An empty candidate pool sets the asset's `second_chance_eligible` to false and makes an offer attempt `ERR_NO_BACKUP_BIDDER`; a non-empty pool sets the flag to true, and an offer created from it takes its `offered_bidder_id` from the top candidate's bidder and its `offer_price_cents` from that candidate's own bid amount. This same selection is what the fallout cascade evaluates when it recomputes `second_chance_eligible`, and what the sold-lot close evaluates when it first sets that flag.

Issuing the offer is an `AuctionOps` action on a `CLOSED_SOLD` lot. The client never nominates the recipient — the server does, by the rule above — and may supply only an optional `expires_at`, which defaults to the logical clock advanced by 3 days, that is 72 hours, when omitted. The offer is created `OUTSTANDING`, and only one may be outstanding per lot at a time: a second attempt while one is still live is `ERR_DUPLICATE_ACTIVE_OFFER`. The offer's four statuses are `OUTSTANDING`, `ACCEPTED`, `DECLINED` and `EXPIRED`, the last three terminal, and `responded_at` records the instant the bidder answered.

Responding is the backup bidder's own act, carrying a `decision` of either `ACCEPTED` or `DECLINED`. The acting `X-User-ID` must equal the offer's `offered_bidder_id`, or the response is `ERR_NOT_RESOURCE_OWNER`; the offer must still be `OUTSTANDING`, or `ERR_OFFER_NOT_OUTSTANDING`; and the responder must clear the same compliance gauntlet as a bidder — not `SUSPENDED`, identity `VERIFIED`, not excluded for the lot's county or platform-wide, and holding at least `required_deposit_cents` in `deposit_available_cents`, failing which the response is `ERR_BIDDER_NOT_REGISTERED`, `ERR_IDENTITY_UNVERIFIED`, `ERR_BIDDER_EXCLUDED` or `ERR_DEPOSIT_INSUFFICIENT` respectively, in the ladder order of §2.9.

Expiry is evaluated lazily, on response. If the logical clock is past the offer's `expires_at`, the platform first moves the offer `OUTSTANDING → EXPIRED` and only then rejects the request with `ERR_OFFER_EXPIRED`; `responded_at` is left unset, because the bidder never validly answered. The state change is durable — the offer stays `EXPIRED` — even though the caller receives an error.

An **acceptance** re-sells the lot without re-running the auction. `responded_at` is stamped from the logical clock; a fresh deposit hold of exactly the lot's `required_deposit_cents` is created for the accepting bidder with a `status` of `HELD`, and that bidder's deposit ledger is recomputed; the accepting bidder's bid on the lot becomes `WINNING` while the bid that had been `WINNING` becomes `OUTBID`; the lot's `hammer_price_cents` is rewritten to the offer's `offer_price_cents` and its `provisional_buyer_premium_cents` is recomputed under the provisional rule against that new price; and the asset moves `RELIST_PENDING → SOLD_PENDING_CONTRACT` with `second_chance_eligible` set to false, so that a fresh purchase contract can be executed against the lot exactly as if it had just been hammered down. A **decline** is far quieter: `responded_at` is stamped, the asset stays `RELIST_PENDING` so the seller may relist it, and `second_chance_eligible` is set to false.

## 4. Endpoint Definitions

Every endpoint that brings a brand-new resource into existence answers with HTTP 201; every endpoint that modifies, transitions or reads an existing resource answers with HTTP 200, and returns the affected resource in `data` as described in §2.2. The logical clock endpoint answers 200 with an empty `data` object. All fifty endpoints are rooted at the API prefix `/`.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/sellers` | Onboard a servicer, bank, GSE or private seller as a settlement counterparty. | `PlatformAdmin` |
| POST | `/asset-listings` | Seller submits an asset for auction intake, starting at `INTAKE` with a `PENDING` title axis. | `Seller` |
| POST | `/asset-listings/{id}/disclosures` | Seller files the occupancy status and title condition disclosures required before the asset can be listed. | `Seller` |
| POST | `/asset-listings/{id}/title-clearance` | Title officer records the outcome of the title search, driving the asset's title axis. | `TitleOfficer` |
| POST | `/asset-listings/{id}/relist` | Seller returns an unsold or relist-pending asset to the listable pool; the title axis is re-opened for a fresh search. | `Seller` |
| POST | `/trustee-sales` | Trustee records the statutory county sale for an asset. | `Trustee` |
| POST | `/trustee-sales/{id}/confirm` | Trustee confirms the sale will proceed on the scheduled date. | `Trustee` |
| POST | `/trustee-sales/{id}/postpone` | Trustee postpones the county sale to a new date; cascades to every linked auction event, its lots, their holds and the affected bidders' ledgers. | `Trustee` |
| POST | `/trustee-sales/{id}/cancel` | Trustee cancels the county sale outright; the same cascade as postponement, but terminal for the events. | `Trustee` |
| POST | `/auction-events` | Auction ops schedules an auction event in a county, optionally bound to a trustee sale. | `AuctionOps` |
| POST | `/auction-events/{id}/lots` | Adds an asset to a scheduled event as a lot; optimistically concurrent on the parent event version. | `AuctionOps` |
| PATCH | `/auction-lots/{id}/reserve-price` | Revises the reserve price on a bid-free lot; optimistically concurrent on the lot version. | `AuctionOps` |
| POST | `/auction-events/{id}/open` | Takes a scheduled event live and opens every pending or suspended lot for bidding. | `AuctionOps` |
| POST | `/auction-events/{id}/reschedule` | Moves a postponed event to a new window and returns it to scheduled, re-checking county and lot-window conflicts. | `AuctionOps` |
| POST | `/bidders` | Self-service bidder registration, starting unverified and pending review. | `Anonymous` |
| POST | `/bidders/{id}/identity-verification` | Compliance officer records the KYC decision for a bidder. | `ComplianceOfficer` |
| POST | `/bidders/{id}/deposits` | Bidder funds the deposit wallet used to back deposit holds. | `Bidder` |
| POST | `/eligibility-exclusions` | Compliance officer records an eligibility exclusion for sanctions, affiliate status, state ineligibility or prior fallout. | `ComplianceOfficer` |
| POST | `/eligibility-exclusions/{id}/lift` | Compliance officer lifts an exclusion; the bidder is reinstated when no active exclusion remains. | `ComplianceOfficer` |
| POST | `/auction-lots/{id}/bids` | Places a bid on an open lot, rolling the deposit hold and possibly extending the lot under the late-bid rule. | `Bidder` |
| POST | `/auction-lots/{id}/close` | Auction ops hammers the lot down after its bid window has elapsed. | `AuctionOps` |
| POST | `/auction-lots/{id}/sale-contract` | Executes the purchase contract for a hammered lot and posts the settlement to the seller; must be performed by a different operator than the one who closed the lot. | `AuctionOps` |
| POST | `/sale-contracts/{id}/close` | Records escrow closing within the closing window. | `AuctionOps` |
| POST | `/sale-contracts/{id}/fallout` | Records post-auction fallout: the buyer's deposit is forfeited, the settlement is voided and the asset is queued for relisting. | `AuctionOps` |
| POST | `/auction-lots/{id}/second-chance-offers` | Offers the lot to the highest reserve-clearing backup bidder after fallout. | `AuctionOps` |
| POST | `/second-chance-offers/{id}/respond` | Backup bidder accepts or declines the second-chance offer. | `Bidder` |
| POST | `/_clock/set_current_utc` | Test-driving endpoint: sets the server's logical UTC clock, which every deadline, window, expiry and timestamp field reads. | `PlatformAdmin` |
| GET | `/sellers/{id}` | Fetch a seller with its running settled net proceeds. | `PlatformAdmin`, `AuctionOps`, `Seller` |
| GET | `/sellers/{id}/asset-listings` | List every asset listing submitted by a seller. | `PlatformAdmin`, `AuctionOps`, `Seller` |
| GET | `/asset-listings/{id}` | Fetch an asset listing including the occupancy, title and eviction-risk disclosures shown to bidders. | `PlatformAdmin`, `AuctionOps`, `Seller`, `TitleOfficer`, `Trustee`, `Bidder`, `Anonymous` |
| GET | `/asset-listings` | Filtered list of asset listings. | `PlatformAdmin`, `AuctionOps`, `Seller` |
| GET | `/asset-listings/{id}/trustee-sales` | List the county trustee sales noticed for an asset. | `PlatformAdmin`, `AuctionOps`, `Trustee`, `Seller` |
| GET | `/trustee-sales/{id}` | Fetch a trustee sale with its postponement counter. | `PlatformAdmin`, `AuctionOps`, `Trustee`, `Seller` |
| GET | `/trustee-sales/{id}/auction-events` | List the auction events bound to a trustee sale. | `PlatformAdmin`, `AuctionOps`, `Trustee` |
| GET | `/auction-events/{id}` | Fetch an auction event with its derived lot count. | `PlatformAdmin`, `AuctionOps`, `Trustee`, `Seller`, `Bidder`, `Anonymous` |
| GET | `/auction-events` | Filtered list of auction events. | `PlatformAdmin`, `AuctionOps`, `Trustee`, `Bidder`, `Anonymous` |
| GET | `/auction-lots/{id}` | Fetch a lot with its deposit requirement, current high bid, extension counter and bid close instant. | `PlatformAdmin`, `AuctionOps`, `Trustee`, `Seller`, `Bidder`, `Anonymous` |
| GET | `/auction-lots` | Filtered list of auction lots; the reverse-reachability channel for both of a lot's foreign keys. | `PlatformAdmin`, `AuctionOps`, `Trustee`, `Seller`, `Bidder`, `Anonymous` |
| GET | `/auction-lots/{id}/sale-contracts` | List the sale contracts executed against a lot, of which there are zero or one. | `PlatformAdmin`, `AuctionOps`, `Seller`, `Bidder` |
| GET | `/auction-lots/{id}/settlement-preview` | Computed read: shows the provisional and final buyer-premium variants side by side with the settlement split that would be posted, mutating nothing. | `PlatformAdmin`, `AuctionOps`, `Seller` |
| GET | `/bidders/{id}` | Fetch a bidder with its deposit ledger and screening risk score. | `PlatformAdmin`, `ComplianceOfficer`, `AuctionOps`, `Bidder` |
| GET | `/bidders/{id}/eligibility-exclusions` | List the eligibility exclusions recorded against a bidder. | `PlatformAdmin`, `ComplianceOfficer`, `AuctionOps` |
| GET | `/bidders/{id}/eligibility-assessment` | Computed read: runs the bidder risk score in the requested variant, screening or audit. | `PlatformAdmin`, `ComplianceOfficer`, `Bidder` |
| GET | `/bids/{id}` | Fetch a single bid. | `PlatformAdmin`, `AuctionOps`, `Bidder` |
| GET | `/bids` | Filtered list of bids; the reverse-reachability channel for both of a bid's foreign keys. | `PlatformAdmin`, `AuctionOps`, `Trustee`, `Seller`, `Bidder` |
| GET | `/deposit-holds/{id}` | Fetch a single deposit hold. | `PlatformAdmin`, `AuctionOps`, `ComplianceOfficer`, `Bidder` |
| GET | `/deposit-holds` | Filtered list of deposit holds; the reverse-reachability channel for both of a hold's foreign keys and the only discovery channel for cascade-created holds. | `PlatformAdmin`, `AuctionOps`, `ComplianceOfficer`, `Bidder` |
| GET | `/sale-contracts/{id}` | Fetch a sale contract with its settlement split, forfeiture split and closing deadline. | `PlatformAdmin`, `AuctionOps`, `Seller`, `Bidder` |
| GET | `/second-chance-offers/{id}` | Fetch a second-chance offer. | `PlatformAdmin`, `AuctionOps`, `Bidder` |
| GET | `/second-chance-offers` | Filtered list of second-chance offers; the reverse-reachability channel for both of an offer's foreign keys and the only discovery channel for the bidder a server-created offer was assigned to. | `PlatformAdmin`, `AuctionOps`, `Bidder` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SELLER_NOT_FOUND` | 404 |
| `ERR_ASSET_LISTING_NOT_FOUND` | 404 |
| `ERR_TRUSTEE_SALE_NOT_FOUND` | 404 |
| `ERR_AUCTION_EVENT_NOT_FOUND` | 404 |
| `ERR_AUCTION_LOT_NOT_FOUND` | 404 |
| `ERR_BIDDER_NOT_FOUND` | 404 |
| `ERR_EXCLUSION_NOT_FOUND` | 404 |
| `ERR_SALE_CONTRACT_NOT_FOUND` | 404 |
| `ERR_OFFER_NOT_FOUND` | 404 |
| `ERR_BID_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_DUPLICATE_LOT_NUMBER` | 409 |
| `ERR_AUDIT_MODE_REQUIRES_LOT` | 422 |
| `ERR_LISTING_NOT_IN_INTAKE` | 409 |
| `ERR_TITLE_CLEARANCE_ALREADY_SET` | 409 |
| `ERR_LISTING_NOT_RELISTABLE` | 409 |
| `ERR_LISTING_NOT_LISTABLE` | 409 |
| `ERR_TITLE_CLEARANCE_PENDING` | 409 |
| `ERR_TITLE_DEFECTIVE` | 409 |
| `ERR_TRUSTEE_SALE_NOT_ACTIONABLE` | 409 |
| `ERR_TRUSTEE_SALE_NOT_CONFIRMED` | 409 |
| `ERR_SALE_DATE_NOT_FUTURE` | 422 |
| `ERR_POSTPONEMENT_LIMIT_EXCEEDED` | 409 |
| `ERR_EVENT_NOT_SCHEDULED` | 409 |
| `ERR_EVENT_NOT_POSTPONED` | 409 |
| `ERR_EVENT_NOT_LIVE` | 409 |
| `ERR_EVENT_HAS_NO_LOTS` | 409 |
| `ERR_EVENT_NOT_STARTED` | 409 |
| `ERR_COUNTY_SLOT_CONFLICT` | 409 |
| `ERR_LOT_NOT_OPEN` | 409 |
| `ERR_LOT_NOT_CLOSED_SOLD` | 409 |
| `ERR_LOT_HAS_BIDS` | 409 |
| `ERR_LOT_WINDOW_CONFLICT` | 409 |
| `ERR_LOT_WINDOW_OUTSIDE_EVENT` | 422 |
| `ERR_BID_WINDOW_CLOSED` | 409 |
| `ERR_LOT_WINDOW_STILL_OPEN` | 409 |
| `ERR_BID_BELOW_MINIMUM` | 422 |
| `ERR_RESERVE_BELOW_OPENING` | 422 |
| `ERR_BIDDER_NOT_REGISTERED` | 409 |
| `ERR_IDENTITY_UNVERIFIED` | 409 |
| `ERR_BIDDER_BARRED` | 403 |
| `ERR_BIDDER_EXCLUDED` | 403 |
| `ERR_DEPOSIT_INSUFFICIENT` | 402 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_CONTRACT_NOT_EXECUTED` | 409 |
| `ERR_CLOSING_DEADLINE_PASSED` | 409 |
| `ERR_NO_BACKUP_BIDDER` | 409 |
| `ERR_DUPLICATE_ACTIVE_OFFER` | 409 |
| `ERR_OFFER_NOT_OUTSTANDING` | 409 |
| `ERR_OFFER_EXPIRED` | 409 |
| `ERR_COUNTY_MISMATCH` | 422 |
| `ERR_STALE_EVENT_VERSION` | 412 |
| `ERR_STALE_LOT_VERSION` | 412 |

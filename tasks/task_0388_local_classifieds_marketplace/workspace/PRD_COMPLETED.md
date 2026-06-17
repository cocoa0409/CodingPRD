# Local Classifieds Marketplace API — Product Requirements Document

## 1. Introduction

Neighborhood classifieds live and die on trust between strangers. A seller posts a couch, a buyer haggles over price, the two agree to meet behind a coffee shop, and somewhere in that chain a scam, a no-show, or a stale listing erodes confidence in the whole market. This document specifies the backend service for a local classifieds and marketplace platform — the Craigslist- or Facebook-Marketplace-style flow of listing an item, discussing it in a private thread, negotiating an offer back and forth, and finally arranging a safe in-person handoff.

The platform models the full lifecycle as a set of peer resources that reference one another by identifier: members who buy and sell, listings organized into categories, conversation threads that carry offers, meetups scheduled at vetted safe-trade locations, moderation flags, and saved searches that fan out alerts when matching inventory appears. Negotiation is genuinely cyclic — buyer and seller trade counteroffers until one side accepts, withdraws, or the round is exhausted — and listings carry two independent status dimensions at once, one tracking whether the post is published and one tracking whether the item is still for sale. Layered on top are safety mechanisms: phone verification, a derived reputation score, spam-flag auto-hiding, suspension and ban cascades, and police-verified meeting spots for high-value goods.

Because the system coordinates several parties acting on shared state, it leans heavily on synchronous, atomic mutations: when one action reserves a listing or removes a member, every dependent record is reconciled inside the same request, and derived counters are recomputed on the spot rather than drifting toward eventual consistency. The remainder of this document defines the global contracts every endpoint obeys (Section 2), the business workflows and their scattered rules (Section 3), the endpoint surface (Section 4), and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request that mutates state, and every read that is not a fully public browse, must carry two headers: `X-User-ID` and `X-User-Role`. The first identifies the acting principal; the second declares the capacity in which they act. When either header is missing or malformed on an endpoint that requires authentication, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are present and well-formed but the declared role is not among the roles authorized for the endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Six roles exist, spelled exactly: `Anonymous`, `Seller`, `Buyer`, `Member`, `Moderator`, and `PlatformAdmin`. The distinctions between them turn on what `X-User-ID` means in each case:

- When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque, unauthenticated identifier not tied to any persisted entity; the role exists for public browsing and self-registration and the server does not compare it to any entity's `id`.
- When `X-User-Role` is `Seller`, `X-User-ID` is the `id` of the acting `Member`. Ownership checks on any resource that references that member compare the resource's owning foreign key to `X-User-ID` — for listing operations the relevant key is the listing's `seller_id`.
- When `X-User-Role` is `Buyer`, `X-User-ID` is the `id` of the acting `Member`. Ownership checks compare the resource's `buyer_id` to `X-User-ID` — for example, only the buyer who created an offer may withdraw it.
- When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`. This is the generic authenticated identity used for messaging, flagging, saved searches, and verification; `Seller` and `Buyer` are facets of the same underlying `Member`. Conversation and offer ownership checks compare `X-User-ID` to the conversation's `buyer_id` or `seller_id`.
- When `X-User-Role` is `Moderator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. A moderator owns the moderation surface (resolving flags, suspending and banning members, taking down listings); the server may record the value but does not compare it to any entity's `id`.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity, used for configuration (categories, safe-trade spots) and for driving the test clock. It is not compared to any entity's `id`.

Note that `role_kind` on a `Member` (one of `SELLER`, `BUYER`, or `BOTH`) is a self-declared transaction preference; it does **not** confer `Moderator` or `PlatformAdmin` powers, which come only from the `X-User-Role` header.

For ownership-scoped operations — listing mutations, countering or withdrawing an offer, sending a message, and confirming or completing a meetup — the acting `X-User-ID` must equal the relevant owning foreign key (the `seller_id` for listing operations; the `buyer_id` or `seller_id` for conversation- and offer-scoped operations). A member who is authenticated and holds an allowed role but is not the owner of the targeted resource is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). Raising a flag does not require ownership of the target.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits; it records the server's real wall-clock instant at which the response was produced, not the logical clock of §2.10.
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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10 when omitted, may not be smaller than 1, and may not exceed 100. The `offset` defaults to 0 and represents the number of leading records skipped. A `limit` that is non-integer or outside the inclusive 1-to-100 range, or an `offset` that is non-integer or negative, is rejected with `ERR_INVALID_REQUEST` (HTTP 400); an empty-string value for either parameter is treated as omitted and falls back to the default. Collections are returned sorted by `created_at` in ascending order (oldest first) unless an endpoint's narrative states otherwise. The `meta` block of a list response carries the pagination fields `limit`, `offset`, `total_count` (the total number of records matching the query before the page window is applied), and `has_more` (a boolean that is true when records remain beyond the current page).

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource is assigned a server-minted `id` that is an opaque UUID carrying no type prefix. Most resources also carry the standard audit and concurrency fields: `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits, and `version` is an integer that begins at the resource's creation value and increments by exactly one on every mutation that changes the resource. The narratives in Section 3 frequently note "increments the resource's `version` by 1" alongside a state change; whenever a resource is mutated, its `updated_at` is also refreshed to the current clock.

Four entities are lightweight records that carry only an `id` and a `created_at`, with **no** `updated_at` and **no** `version` field: `Category`, `Message`, `SafeTradeSpot`, and `Alert` are immutable once written. (Categories and safe-trade spots are configuration created by a `PlatformAdmin`; messages and alerts are append-only event records.) All other entities — `Member`, `Listing`, `Conversation`, `Offer`, `Meetup`, `Flag`, and `SavedSearch` — carry the full `created_at`, `updated_at`, and `version` triple.

### 2.5. Nested Resource Retrieval and Referential Existence

Several read endpoints are expressed as nested paths (for example, the offers belonging to a listing, the messages within a conversation, the alerts generated for a saved search, or the meetups at a safe-trade spot). For any path that names a parent resource followed by a child collection, the parent segment is validated first, left to right: if the parent does not exist, the request fails with `ERR_NOT_FOUND` (HTTP 404) before the child collection is consulted. The same left-to-right existence rule governs every foreign key supplied in a request body or path — a referenced `listing_id`, `conversation_id`, `offer_id`, `spot_id`, `category_slug`, or member identifier that does not resolve to an existing resource yields `ERR_NOT_FOUND`.

### 2.6. Derived Counters and Synchronous Reconciliation

The platform maintains several denormalized counters that must remain exactly consistent with the records they summarize, recomputed synchronously inside the request that disturbs them. A listing carries `open_offer_count` (the number of its offers currently open for negotiation) and `active_flag_count` (the number of unresolved flags against it); a conversation carries `message_count`; a member carries `active_listing_count`, `upheld_flag_count`, and the derived `trust_score`; and a saved search carries `alert_count`. None of these are accepted as input — each is `system`- or `computed`-sourced and is updated only by the side effects described in Section 3. When a single operation touches more than one entity, all affected counters are reconciled before the response is returned.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control to prevent a client from acting on a parent record it has not freshly observed.

Accepting an offer requires the request to carry `expected_listing_version`, a non-optional field that must equal the current `version` of the offer's `Listing`. Because accepting an offer reserves the listing and rejects every sibling offer, a second accept targeting a different sibling offer on the same listing would, under natural product semantics, also try to reserve the listing; once the first accept advanced the listing's `version`, the second client's `expected_listing_version` is stale. A request whose `expected_listing_version` does not match the listing's current `version` is rejected with `ERR_STALE_LISTING_VERSION` (HTTP 412).

Creating a meetup requires the request to carry `expected_offer_version`, a non-optional field that must equal the current `version` of the referenced `Offer`. Scheduling a meetup pins the accepted offer as the reservation's basis; if the offer's `version` has advanced since the client read it (for example, because a compensation withdrew and the offer was re-accepted), the client's `expected_offer_version` is stale and the create is rejected with `ERR_STALE_OFFER_VERSION` (HTTP 412).

No endpoint outside these two takes a version field; the version triple is otherwise read-only to clients.

### 2.8. Validation Ordering

When several checks apply to one endpoint, they are evaluated in a fixed priority so that the rejection a client sees is deterministic. The order is: (1) authentication of the headers (`ERR_UNAUTHENTICATED`); (2) role authorization for the endpoint (`ERR_FORBIDDEN_ROLE`); (3) resource ownership for ownership-scoped operations (`ERR_NOT_RESOURCE_OWNER`); (4) existence of every referenced resource, left to right (`ERR_NOT_FOUND`); (5) state validity — the target must be in a state from which the requested transition is defined (`ERR_INVALID_STATE`); (6) optimistic-concurrency freshness where a version field applies (`ERR_STALE_LISTING_VERSION` or `ERR_STALE_OFFER_VERSION`); (7) the acting member's standing (`ERR_MEMBER_NOT_ACTIVE`); then the domain-specific safety, temporal, constraint, referential, and fiscal checks described throughout Section 3, ending with (8) basic request well-formedness (`ERR_INVALID_REQUEST`). The standing gate at step (7) is applied with two distinct thresholds and only on the operations enumerated here: publish and renew (§3.3) require the seller's `status` to be exactly `ACTIVE` (a `SUSPENDED` or `BANNED` seller is rejected), whereas proposing an offer, countering an offer, accepting an offer, sending a message, and creating a meetup reject only a `BANNED` acting member — a merely `SUSPENDED` member passes the standing gate on those operations. All other endpoints (including opening a conversation, rejecting or withdrawing an offer, confirming/completing/cancelling/no-showing a meetup, and raising a flag) apply no member-standing gate at all, so the acting member's `status` is not consulted there. Earlier checks mask later ones: a request that fails authentication never reaches the state check, and a request against a resource in the wrong state never reaches the concurrency check.

### 2.9. Monetary Precision and the Trust Score

All money on the platform is expressed in integer cents (`ask_price_cents`, `min_acceptable_price_cents`, `amount_cents`, `max_price_cents`); there is no fractional currency and no rounding to perform on monetary fields. The one derived numeric, `trust_score`, is likewise computed entirely in integer points with no fractional rounding — every term that feeds it is an integer — and the result is clamped to the inclusive range from 0 to 100.

### 2.10. The Logical Clock

The platform operates against a server-held logical clock rather than wall-clock time, so that temporal behavior (listing expiry, offer expiry, meetup timing) is deterministic and test-drivable. Before any `/_clock` call is made the clock holds the Unix epoch (`1970-01-01T00:00:00.000Z`) as its starting instant. A `PlatformAdmin` may set the clock to an absolute instant or advance it; advancing additionally runs expiry sweeps as described in Section 3. All datetime fields — `expires_at`, `matched_at`, `start_at`, `end_at` — are interpreted in UTC against this clock.

## 3. Business Logic & Workflows

### 3.1. Members, Verification, and Reputation

A new member is registered by submitting an `email` and a `display_name`, optionally declaring a `role_kind`; the email must be non-empty and unique across all members (a duplicate email is rejected with `ERR_INVALID_REQUEST`, HTTP 400), and `role_kind`, when given, must be one of `SELLER`, `BUYER`, or `BOTH`, defaulting to `BOTH`. On registration the member's `status` begins `ACTIVE`, `phone_verified` begins false, `verification_code` is null, the derived `trust_score` is initialized to the base reputation value of 50, and the counters `upheld_flag_count` and `active_listing_count` both begin at 0. Registration is open to `Anonymous` callers.

Safe-trade phone verification proceeds in two steps, both invoked under the `Member` role; verification is not an ownership-scoped operation, so the acting `X-User-ID` is not compared to the targeted member's `id` and any authenticated `Member` may drive either step against any member identifier. Requesting verification mints a server-issued one-time `verification_code`, stores it on the member, and returns the member (including the minted `verification_code`) in the response so the caller can complete the second step; requesting verification does not by itself increment the member's `version` or refresh `updated_at`. Confirming verification submits a `verification_code`; if the submitted code does not match the member's minted `verification_code`, the request fails with `ERR_VERIFICATION_CODE_MISMATCH` (HTTP 422). On a match, `phone_verified` is set to true, the stored `verification_code` is cleared, the member's `version` increments by 1, and the `trust_score` is recomputed immediately.

The `trust_score` is a 0-to-100 reputation derived from three signals, recomputed whenever a flag targeting the member (or one of their listings) is upheld, whenever phone verification is confirmed, and whenever a meetup involving the member as buyer or seller is completed. The computation proceeds in a fixed order: start from a base of 50; add a verification bonus of 20 if and only if the member's `phone_verified` is true, and 0 otherwise; compute a completion bonus equal to 6 multiplied by the number of completed sales credited to the member, where that count is the number of `COMPLETED` meetups in which the member is the `buyer_id` or the `seller_id`, but with the completed-sale count capped at 5 before multiplying (so the completion bonus tops out at 30); and compute a flag penalty equal to 15 multiplied by the member's `upheld_flag_count`. The raw score is the base plus the verification bonus plus the completion bonus minus the flag penalty. The final `trust_score` is that raw value clamped to the inclusive range 0 to 100 — never below 0, never above 100. Because verification and sale completion feed the same formula, a member's score recomputed at phone-verification time reflects the verification bonus but only the sales completed up to that moment, whereas the same member recomputed after a meetup completes gains the additional completion increment (up to the cap), producing a strictly higher score for identical flag and verification inputs.

A `Moderator` governs a member's standing. Suspension moves an `ACTIVE` member to `SUSPENDED`; this is permitted only while the member's `status` is `ACTIVE`. Reinstatement moves a `SUSPENDED` member back to `ACTIVE`, permitted only while the `status` is `SUSPENDED`; reinstatement does **not** automatically republish anything — the seller must republish manually. Banning moves a member to the terminal `BANNED` state and is permitted from either `ACTIVE` or `SUSPENDED`, but only when the member's `upheld_flag_count` is at least the ban threshold of 2; a ban attempted while the `upheld_flag_count` is below 2 is rejected with `ERR_BAN_THRESHOLD_NOT_MET` (HTTP 409). Each of suspend, reinstate, and ban increments the member's `version` by 1. The cascades that suspension and banning trigger are described in §3.7.

A member may be browsed publicly. A member-detail read exposes the `trust_score`, `upheld_flag_count`, and `active_listing_count`.

### 3.2. Categories and Listing Creation

Categories are configuration maintained by a `PlatformAdmin`. A category is created with a `slug` (a unique, non-empty URL-safe identifier such as `furniture`; a duplicate slug is rejected with `ERR_INVALID_REQUEST`, HTTP 400, and the lowercase/kebab-case shape is not separately validated) and a human-readable `name`, plus two optional policy fields: `requires_phone_verified_seller`, defaulting to false, which gates publication on seller verification; and `max_price_cents`, a non-negative integer upper bound (inclusive) on listing price within the category, defaulting to 0, where 0 means the category imposes no price cap. Categories are listable by anyone.

A `Seller` creates a listing by supplying its `seller_id`, the `category_slug` it belongs to, a `title` (non-empty, at most 120 characters), a `description`, an `ask_price_cents` (the publicly listed asking price, at least 1 cent), and a `min_acceptable_price_cents` (the seller's private floor). A newly created listing begins with `publication_status` of `DRAFT` and `sale_status` of `AVAILABLE`; its `expires_at` is null, its `renewal_count` is 0, its `open_offer_count` and `active_flag_count` are 0, and its `accepted_offer_id` is null. The `seller_id` is fixed at creation and is immutable thereafter.

Two fiscal relationships are checked whenever a listing is created or repriced. First, the private floor must be coherent with the asking price: `min_acceptable_price_cents` must be at least 1 and at most the `ask_price_cents`; a floor above the ask (or below 1) is rejected with `ERR_FLOOR_ABOVE_ASK` (HTTP 422). Second, when the listing's category carries a non-zero `max_price_cents`, the `ask_price_cents` must not exceed that cap; an ask above a non-zero category cap is rejected with `ERR_PRICE_EXCEEDS_CATEGORY_CAP` (HTTP 422). The category price cap is re-checked at creation, at publish, and on any reprice; the floor relationship is re-checked at creation and on any reprice. The private floor is confidential: `min_acceptable_price_cents` is never returned to buyers, and a listing read (whether single-detail or within a list) includes it only when the request's `X-User-Role` is `Seller` and its `X-User-ID` equals the listing's `seller_id`; for every other reader — including the owning member acting under any role other than `Seller` — the field is omitted entirely from the serialized listing.

A seller may edit a listing's `title`, `description`, `ask_price_cents`, and `min_acceptable_price_cents` (repricing). A reprice may lower the ask freely but cannot leave the floor above the new ask, and cannot push the ask above a non-zero category cap; the same `ERR_FLOOR_ABOVE_ASK` and `ERR_PRICE_EXCEEDS_CATEGORY_CAP` guards apply. A successful edit increments the listing's `version` by 1.

### 3.3. Publication, Expiry, and Renewal

Publishing turns a `DRAFT` listing into an `ACTIVE` one and is the gate through which inventory becomes visible and tradeable. Publication is permitted only when the listing is currently `DRAFT`; the seller's own `status` is `ACTIVE`; the seller's `active_listing_count` is below the active-listing cap of 3; the category's price cap (when non-zero) is satisfied by the `ask_price_cents`; and, if the category's `requires_phone_verified_seller` is true, the seller's `phone_verified` is true. A suspended or banned seller attempting to publish is rejected with `ERR_MEMBER_NOT_ACTIVE` (HTTP 403). A seller who already holds 3 active listings is rejected with `ERR_ACTIVE_LISTING_LIMIT` (HTTP 409). A publish into a verification-gated category by an unverified seller is rejected with `ERR_SELLER_NOT_PHONE_VERIFIED` (HTTP 422). On success, the listing's `expires_at` is set to the current clock plus the listing time-to-live of 30 days, the seller's `active_listing_count` increments by 1, the listing's `version` increments by 1, and the alert fan-out described in §3.8 fires.

Listings expire by the passage of the logical clock. When the clock is advanced to or beyond a listing's `expires_at`, an `ACTIVE` listing transitions to `EXPIRED`; the same transition may be forced immediately by the seller or a `PlatformAdmin`. Expiry is defined only from `ACTIVE`, and the sweep applies only when the current clock is at or beyond the listing's `expires_at`. On expiry the seller's `active_listing_count` decrements by 1, the listing's open offers expire (see §3.5), and the listing's `version` increments by 1. Importantly, conversations on an expired listing remain `OPEN` — buyers may keep messaging — even though its open offers are swept away.

Renewal refreshes a listing's clock and is permitted in two shapes. An `EXPIRED` listing may be renewed back to `ACTIVE`, provided the listing's `sale_status` is not `SOLD`, the listing's `renewal_count` is below the renewal cap of 2, the seller's `status` is `ACTIVE`, and the seller's `active_listing_count` is below 3; this sets `expires_at` to the current clock plus 30 days, increments `renewal_count` by 1, increments the seller's `active_listing_count` by 1 (the listing rejoins the active set), and increments the listing's `version` by 1. An already-`ACTIVE` listing may also be renewed to extend its time-to-live in place, provided its `sale_status` is not `SOLD` and its `renewal_count` is below 2; this resets `expires_at` to the current clock plus 30 days and increments `renewal_count` by 1, but leaves `active_listing_count` unchanged because the listing was already counted, and increments the listing's `version` by 1. A renew attempted when the seller is not `ACTIVE` is rejected with `ERR_MEMBER_NOT_ACTIVE`; a renew that would exceed the active-listing cap of 3 is rejected with `ERR_ACTIVE_LISTING_LIMIT`; a renew when the `renewal_count` has already reached 2 is rejected with `ERR_MAX_RENEWALS_REACHED` (HTTP 409).

### 3.4. Conversations and Messaging

A `Buyer` opens a conversation against a listing by supplying the `listing_id` and their own `buyer_id`. At creation the conversation's `seller_id` is copied from the listing's `seller_id`, its `status` is set to `OPEN`, and its `message_count` begins at 0. A member may not open a conversation on their own listing — when the `buyer_id` equals the listing's `seller_id` the request is rejected with `ERR_CANNOT_TRADE_OWN_LISTING` (HTTP 422), the same self-trade ban that governs offers.

Messages are sent into a conversation by supplying the `conversation_id`, the `sender_id`, and a non-empty `body` of at most 2000 characters. The sender must be a participant of the thread — that is, the `sender_id` must equal the conversation's `buyer_id` or its `seller_id`; an outsider attempting to post is rejected with `ERR_NOT_CONVERSATION_PARTICIPANT` (HTTP 403). Each accepted message increments the conversation's `message_count` by 1. Messages are immutable append-only records (they carry no `version`).

A conversation closes — its `status` becomes `CLOSED` — as a side effect when its listing is sold or removed, as detailed in §3.7. Conversations may be listed and filtered by listing, by participant, or by status.

### 3.5. Offers and the Negotiation Loop

Offers live inside a conversation and capture a haggling thread between one buyer and the listing's seller. A `Buyer` proposes an offer by supplying the `conversation_id` and an `amount_cents` (at least 1). At creation, the offer's `listing_id`, `buyer_id`, and `seller_id` are copied from the conversation; its `status` is `PROPOSED`, its `last_actor_side` is `BUYER`, its `round_count` is 0, and its `expires_at` is set to the current clock plus the offer time-to-live of 48 hours. The proposer must be a participant of the conversation; a non-participant is rejected with `ERR_NOT_CONVERSATION_PARTICIPANT`, and a member offering on their own listing is rejected with the self-trade ban `ERR_CANNOT_TRADE_OWN_LISTING`.

The seller's private floor auto-rejects lowball buyer offers without any manual moderator action. The boundary is inclusive on acceptance: when the actor is the buyer and the proposed `amount_cents` is strictly below the listing's `min_acceptable_price_cents`, the offer is created and then immediately transitioned to `REJECTED`, and it is not counted in the listing's `open_offer_count` (it never net-enters the open set). An offer exactly at the floor is allowed through. This floor applies to buyer proposals and buyer-side counters only; seller-side counters are never subject to the floor — a seller may counter at any amount. There is no upper auto-reject; a buyer may offer above the asking price.

Countering drives the cyclic negotiation. A counter takes a new `amount_cents` and is permitted only when the offer's `status` is `PROPOSED` or `COUNTERED`; when the actor is the side that did **not** make the last move (the actor's side must differ from the offer's `last_actor_side`); when the offer's `round_count` is below the negotiation round cap of 5; and when the listing is still `ACTIVE` in publication and `AVAILABLE` for sale. A counter sets the offer's `status` to `COUNTERED`, records the new `amount_cents`, flips `last_actor_side` to the acting side, increments `round_count` by 1, and refreshes `expires_at` to the current clock plus 48 hours; the counter increments the offer's `version` by 1. Because a counter moves an already-open offer to another open state, it leaves the listing's `open_offer_count` unchanged. A counter attempted by the side that just moved is rejected with `ERR_NOT_YOUR_TURN` (HTTP 409); a counter attempted once `round_count` has reached 5 is rejected with `ERR_MAX_ROUNDS_REACHED` (HTTP 409). A buyer-side counter below the floor is auto-rejected exactly as a proposal is.

The responding side may reject, the buyer may withdraw, or the seller (or the entitled responder) may accept. Rejecting an offer that is `PROPOSED` or `COUNTERED` moves it to `REJECTED`, decrements the listing's `open_offer_count` by 1, and clears `expires_at`; on a `COUNTERED` offer the rejecter must be the side entitled to respond (the actor's side must differ from `last_actor_side`), and a reject by the side that just moved is rejected with `ERR_NOT_YOUR_TURN` (HTTP 409); a `PROPOSED` offer carries no such turn restriction and may be rejected by either party. Withdrawing is the buyer's prerogative: only the offer's buyer may withdraw, moving a `PROPOSED` or `COUNTERED` offer to `WITHDRAWN`, decrementing `open_offer_count` by 1, and clearing `expires_at`. Both reject and withdraw increment the offer's `version` by 1. The turn-order rule (`ERR_NOT_YOUR_TURN`) guards counter and accept; both also increment the relevant versions on success.

Acceptance is where negotiation settles into a reservation. The seller may accept a `PROPOSED` or `COUNTERED` offer, and on a `COUNTERED` offer the accepting actor must be the side entitled to respond (the side that did not make the last move). Acceptance requires the listing's `sale_status` to be `AVAILABLE`, and the request must carry `expected_listing_version` matching the listing's current `version` as described in §2.7. On acceptance the offer moves to `ACCEPTED`, the listing's `sale_status` moves from `AVAILABLE` to `RESERVED`, the listing's `accepted_offer_id` is set to the accepted offer, and every sibling offer on that listing still in `PROPOSED` or `COUNTERED` is cascaded to `REJECTED`; the listing's `open_offer_count` is reconciled downward to remove both the accepted offer and each rejected sibling from the open set, and both the listing's `version` and the offer's `version` increment by 1.

Offers also expire by the clock. When the clock advances to or beyond an offer's `expires_at`, a `PROPOSED` or `COUNTERED` offer transitions to `EXPIRED`, its `open_offer_count` contribution is removed (the listing's counter decrements by 1) and its `expires_at` is cleared, with the offer's `version` incrementing by 1. The same `EXPIRED` outcome is reached when a listing removal, listing expiry, or member suspension cascades into the offer (see §3.7).

The listing's `open_offer_count` is a strictly conserved denormalized counter: at all times it must equal the number of offers on that listing whose `status` is `PROPOSED` or `COUNTERED`. It is maintained by deltas rather than recomputed from scratch: a fresh proposal adds 1; a counter from one open state to another adds 0; an acceptance subtracts 1 for the accepted offer leaving the open set plus 1 for each sibling auto-rejected; and a reject, withdraw, or expire each subtract 1. Reconciling `open_offer_count` is a denormalized-counter update that does not by itself advance the listing's `version`: an `open_offer_count`-disturbing operation increments the listing's `version` only when the operation is itself one of the enumerated listing transitions (acceptance per this section, expiry per §3.3/§3.9, or removal per §3.7); a fresh proposal, a counter (including a buyer-side counter auto-rejected below the floor), a reject, a withdraw, and a clock-driven offer expiry each adjust `open_offer_count` but leave the listing's `version` unchanged. An accepted offer that is later compensated back to `WITHDRAWN` (when its reserving meetup falls through, see §3.6) leaves the counter unchanged, because an `ACCEPTED` offer was already out of the open set — the count was already decremented at acceptance. The conserved quantity is the open-offer ledger, and the forward action (accept) together with its compensating action (meetup cancel or no-show withdrawing the offer) must leave `open_offer_count` exactly where acceptance left it.

### 3.6. Safe-Trade Spots and Meetups

Safe-trade spots are vetted meeting locations configured by a `PlatformAdmin`. A spot is created with a public `name`, an optional `is_police_verified` flag (defaulting to false, true for police-station-grade locations), and a daily operating window expressed in minutes since UTC midnight: `open_minute_of_day` (inclusive) and `close_minute_of_day` (exclusive), where the open time is at least 0 and strictly less than the close time, and the close time is at most 1440. Spots are publicly listable.

Once an offer has been accepted and its listing reserved, either party schedules a meetup against that offer by supplying the `offer_id`, the `spot_id` where the exchange will happen, a proposed `start_at` (inclusive) and `end_at` (exclusive), and the `expected_offer_version` for the optimistic-concurrency check of §2.7. Scheduling is defined only against an offer whose `status` is `ACCEPTED`; a meetup-create targeting an offer in any other status is rejected at the state step with `ERR_INVALID_STATE` (HTTP 409), which is evaluated before the `expected_offer_version` freshness check. At creation the meetup's `listing_id`, `buyer_id`, and `seller_id` are copied from the offer, and its `status` is set to `PROPOSED`. Two temporal rules are validated at creation against the chosen spot. The window must be coherent: the `end_at` must be strictly after the `start_at`, and both `start_at` and `end_at` must fall on the same UTC date (a meetup may not span midnight). The window must also be contained within the spot's operating hours: converting the meetup's start and end to minutes-of-day, the start minute-of-day must be at or after the spot's `open_minute_of_day` and the end minute-of-day must be at or before the spot's `close_minute_of_day`. A meetup whose window falls outside the spot's operating hours, spans midnight, or has an `end_at` at or before its `start_at` is rejected with `ERR_OUTSIDE_SPOT_HOURS` (HTTP 422).

Confirmation is performed by the counterparty — the side that did **not** propose the meetup confirms it — and is permitted only from a `PROPOSED` meetup whose listing is still `RESERVED` with the listing's `accepted_offer_id` equal to this meetup's `offer_id`. A confirm attempt by the very side that proposed the meetup is rejected with `ERR_NOT_YOUR_TURN` (HTTP 409); a confirm against a listing that is no longer `RESERVED` for this offer is rejected with `ERR_INVALID_STATE` (HTTP 409). Two further gates apply at confirm time. First, the candidate meetup's interval must not collide with any **other** `CONFIRMED` meetup at the same `spot_id`. Intervals are treated as half-open `[start_at, end_at)` in absolute UTC, and two intervals collide if and only if the first starts strictly before the second ends and the second starts strictly before the first ends; under this rule a meetup ending exactly when another begins does not collide (adjacency is allowed, zero overlap). Only `CONFIRMED` meetups block — `PROPOSED`, `COMPLETED`, `CANCELLED`, and `NO_SHOW` meetups do not. A colliding confirmation is rejected with `ERR_SPOT_TIME_CONFLICT` (HTTP 409). Second, high-value goods demand a vetted location: if the listing's `ask_price_cents` is at or above the high-value threshold of 50000 cents, the chosen spot's `is_police_verified` must be true; confirming a high-value meetup at a non-police-verified spot is rejected with `ERR_SPOT_NOT_POLICE_VERIFIED` (HTTP 422). A successful confirmation moves the meetup from `PROPOSED` to `CONFIRMED` and increments its `version` by 1.

Completion finalizes the sale and may be performed only by the listing's seller, only from a `CONFIRMED` meetup whose listing is still `RESERVED` with `accepted_offer_id` equal to the meetup's `offer_id`. Completion moves the meetup to `COMPLETED`, cascades the listing's `sale_status` from `RESERVED` to `SOLD`, forces the listing's `publication_status` to `REMOVED` if it is currently `ACTIVE` or `EXPIRED` (and decrements the seller's `active_listing_count` if the listing was `ACTIVE`), closes the listing's `OPEN` conversations, and recomputes the `trust_score` of both the buyer and the seller (a completed sale lifts reputation). The meetup's `version` increments by 1.

A meetup may fall through, and when it does the reservation is compensated. A `PROPOSED` meetup may be cancelled by either party or a `Moderator`; a `CONFIRMED` meetup may likewise be cancelled. When the cancelled meetup references the listing's `accepted_offer_id`, the listing's `sale_status` reverts from `RESERVED` to `AVAILABLE`, the `accepted_offer_id` is cleared, and the previously `ACCEPTED` offer is compensated to `WITHDRAWN`; the meetup moves to `CANCELLED` and its `version` increments by 1. A no-show may be reported once the clock is at or beyond the meetup's `end_at` (a no-show reported while the clock is still strictly before `end_at` is rejected with `ERR_INVALID_STATE`, HTTP 409), moving a `CONFIRMED` meetup to `NO_SHOW` and applying the same reservation reversal — the listing returns to `AVAILABLE`, `accepted_offer_id` is cleared, and the `ACCEPTED` offer is compensated to `WITHDRAWN` — with the meetup's `version` incrementing by 1. The reservation reversal that cancellation and no-show share is the compensating leg of the open-offer ledger discussed in §3.5: the offer's move to `WITHDRAWN` leaves `open_offer_count` unchanged because the accepted offer had already left the open set.

### 3.7. Moderation, Flags, and Cascading Removals

Any `Member` may raise a flag. A flag carries the `reporter_id`, a polymorphic `target_type` of either `LISTING` or `MEMBER`, and a `reason` of `SPAM`, `PROHIBITED`, `SCAM`, `MISCATEGORIZED`, or `OTHER`. When the `target_type` is `LISTING` the request carries a `target_listing_id`; when it is `MEMBER` it carries a `target_member_id`. A new flag begins with `status` `OPEN` and a null `resolution_note`. Flag creation imposes no state check on its target, so a flag may be raised against a listing in any `publication_status` (including `REMOVED`). When a flag targets a listing, that listing's `active_flag_count` increments by 1 on flag creation, and once a listing's `active_flag_count` reaches the spam-flag threshold of 3 the listing is auto-hidden — cascaded to `REMOVED` — with the full removal cascade below; the auto-hide fires only when the listing is still in a removable state (`DRAFT`, `ACTIVE`, or `EXPIRED`), so a flag pushing an already-`REMOVED` listing to or past the threshold increments `active_flag_count` without triggering a further removal.

A `Moderator` resolves a flag from `OPEN` into one of two terminal branches with divergent effects. Upholding a flag moves it to `UPHELD`: when the target is a listing, that listing's `active_flag_count` decrements by 1, the listing's seller's `upheld_flag_count` increments by 1, and that seller's `trust_score` is recomputed; when the target is a member, that member's `upheld_flag_count` increments by 1 and that member's `trust_score` is recomputed. Dismissing a flag moves it to `DISMISSED`: when the target is a listing, that listing's `active_flag_count` decrements by 1, but there is no `upheld_flag_count` change and no reputation impact; when the target is a member, no counter changes at all. Either resolution may record an optional `resolution_note` and increments the flag's `version` by 1.

Listing removal is the convergence point of several cascades and may be triggered by the seller delisting, by a moderator takedown, by the spam-flag auto-hide above, or by a member suspension or ban. Removal moves a listing to the terminal `REMOVED` state. From `ACTIVE`, removal decrements the seller's `active_listing_count` by 1, freezes the sale dimension at its current value and clears `accepted_offer_id`, closes all `OPEN` conversations on the listing to `CLOSED`, expires every offer on the listing in `PROPOSED` or `COUNTERED` to `EXPIRED` (a transitive cascade through the offer ledger), and cancels any `PROPOSED` or `CONFIRMED` meetup on the listing to `CANCELLED`; the listing's `version` increments by 1. From `EXPIRED`, removal leaves `active_listing_count` unchanged (it was already decremented at expiry) and closes all `OPEN` conversations to `CLOSED`, incrementing the listing's `version` by 1. From `DRAFT`, removal leaves `active_listing_count` unchanged (a draft was never counted) and increments the listing's `version` by 1.

Member suspension and banning each cascade through the seller's inventory. Suspending an `ACTIVE` member removes all of that member's listings whose `publication_status` is `ACTIVE`: each such listing transitions to `REMOVED`, and each removal in turn closes its `OPEN` conversations and expires its `PROPOSED`/`COUNTERED` offers — the transitive cascade above. Banning a member removes all of that member's listings whose `publication_status` is `DRAFT`, `ACTIVE`, or `EXPIRED`: each transitions to `REMOVED` with the same closing of conversations and expiring of open offers. Both increment the member's `version` by 1, as already noted in §3.1.

### 3.8. Saved Searches and Alert Fan-Out

A `Member` saves a search so the platform can notify them when matching inventory appears. A saved search carries an `owner_id`, a `category_slug` to filter on, an optional `keyword` (a case-insensitive substring matched against a listing's `title`, null by default), and an optional `max_price_cents` ceiling (a non-negative integer, defaulting to 0, where 0 means no price cap). Its `alert_count` begins at 0.

The alert fan-out fires when a listing is published (the `DRAFT` to `ACTIVE` transition of §3.3). For every saved search whose `category_slug` equals the newly published listing's `category_slug`, and whose `keyword` is either null or a case-insensitive substring of the listing's `title`, and whose `max_price_cents` is either 0 or greater than or equal to the listing's `ask_price_cents`, the system creates one `Alert` and increments that saved search's `alert_count` by 1. Each generated alert is an immutable record copying the matching saved search's identifier into `saved_search_id`, the publishing listing's identifier into `listing_id`, and the current clock into `matched_at`. Alerts are listable per saved search and (for a `PlatformAdmin`) per listing.

### 3.9. The Test Clock and Expiry Sweeps

A `PlatformAdmin` drives time through two operations, each taking a target timestamp `to_iso8601`. Setting the clock moves the server's current UTC clock to the supplied instant but runs no sweeps. Advancing the clock moves the current clock forward to the supplied instant and then runs expiry sweeps: every `ACTIVE` listing whose `expires_at` is at or before the new clock transitions to `EXPIRED` (carrying its open-offer expiry cascade), and every `PROPOSED` or `COUNTERED` offer whose `expires_at` is at or before the new clock transitions to `EXPIRED`. Each entity affected by a sweep has its `version` incremented by 1. These sweeps are the mechanism by which the temporal windowing of listings and offers takes effect deterministically.

## 4. Endpoint Definitions

All endpoints share the response envelope of §2.2. Creating a brand-new resource returns HTTP 201; reads and in-place modifications (including state transitions) return HTTP 200. The request body, response body, and side effects of each endpoint are not repeated here — reconstruct them from the Section 3 narratives. Path variables are validated left-to-right for existence as described in §2.5.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/members` | Register a member | Anonymous |
| GET | `/members` | List members (filterable by email, status) | Anonymous, Moderator, PlatformAdmin |
| GET | `/members/{id}` | Get a member | Anonymous, Member, Moderator, PlatformAdmin |
| POST | `/members/{id}/request-verification` | Begin phone verification; mint a code | Member |
| POST | `/members/{id}/confirm-verification` | Confirm phone verification | Member |
| POST | `/members/{id}/suspend` | Suspend a member | Moderator |
| POST | `/members/{id}/reinstate` | Reinstate a suspended member | Moderator |
| POST | `/members/{id}/ban` | Ban a member | Moderator |
| GET | `/members/{id}/flags` | List flags targeting a member | Moderator, PlatformAdmin |
| POST | `/categories` | Create a category | PlatformAdmin |
| GET | `/categories` | List categories | Anonymous, Member, Moderator, PlatformAdmin |
| POST | `/listings` | Create a listing in DRAFT | Seller |
| GET | `/listings` | List/search listings | Anonymous, Member, Moderator, PlatformAdmin |
| GET | `/listings/{id}` | Get a listing | Anonymous, Member, Moderator, PlatformAdmin |
| PATCH | `/listings/{id}` | Edit/reprice a listing | Seller |
| POST | `/listings/{id}/publish` | Publish a DRAFT listing | Seller |
| POST | `/listings/{id}/renew` | Renew a listing | Seller |
| POST | `/listings/{id}/expire` | Force-expire an ACTIVE listing | Seller, PlatformAdmin |
| POST | `/listings/{id}/remove` | Remove a listing | Seller, Moderator |
| GET | `/listings/{id}/offers` | List offers on a listing | Seller, Moderator, PlatformAdmin |
| GET | `/listings/{id}/flags` | List flags targeting a listing | Moderator, PlatformAdmin |
| GET | `/listings/{id}/conversations` | List conversations on a listing | Seller, Moderator, PlatformAdmin |
| GET | `/listings/{id}/alerts` | List alerts generated by a listing | PlatformAdmin |
| POST | `/conversations` | Open a conversation on a listing | Buyer |
| GET | `/conversations` | List conversations | Member, Moderator, PlatformAdmin |
| GET | `/conversations/{id}` | Get a conversation | Member, Moderator, PlatformAdmin |
| GET | `/conversations/{id}/messages` | List messages in a conversation | Member, Moderator, PlatformAdmin |
| GET | `/conversations/{id}/offers` | List offers in a conversation | Member, Moderator, PlatformAdmin |
| POST | `/messages` | Send a message | Member |
| GET | `/messages` | List messages (by conversation/sender) | Member, Moderator, PlatformAdmin |
| GET | `/messages/{id}` | Get a single message | Member, Moderator, PlatformAdmin |
| POST | `/offers` | Propose an offer | Buyer |
| GET | `/offers` | List offers (filterable) | Member, Moderator, PlatformAdmin |
| GET | `/offers/{id}` | Get an offer | Member, Moderator, PlatformAdmin |
| POST | `/offers/{id}/counter` | Counter an offer | Seller, Buyer |
| POST | `/offers/{id}/accept` | Accept an offer (OCC on listing) | Seller, Buyer |
| POST | `/offers/{id}/reject` | Reject an offer | Seller, Buyer |
| POST | `/offers/{id}/withdraw` | Withdraw an offer | Buyer |
| GET | `/offers/{id}/meetups` | List meetups for an offer | Member, Moderator, PlatformAdmin |
| POST | `/safe-trade-spots` | Create a safe-trade spot | PlatformAdmin |
| GET | `/safe-trade-spots` | List safe-trade spots | Anonymous, Member, Moderator, PlatformAdmin |
| GET | `/safe-trade-spots/{id}` | Get a safe-trade spot | Anonymous, Member, Moderator, PlatformAdmin |
| GET | `/safe-trade-spots/{id}/meetups` | List meetups at a spot | Member, Moderator, PlatformAdmin |
| POST | `/meetups` | Propose a meetup (OCC on offer) | Seller, Buyer |
| GET | `/meetups` | List meetups (filterable) | Member, Moderator, PlatformAdmin |
| GET | `/meetups/{id}` | Get a meetup | Member, Moderator, PlatformAdmin |
| POST | `/meetups/{id}/confirm` | Confirm a proposed meetup | Seller, Buyer |
| POST | `/meetups/{id}/complete` | Complete a meetup; finalize the sale | Seller |
| POST | `/meetups/{id}/cancel` | Cancel a meetup | Seller, Buyer, Moderator |
| POST | `/meetups/{id}/no-show` | Report a no-show | Seller, Buyer |
| POST | `/flags` | Report a listing or member | Member |
| GET | `/flags` | List flags (moderation queue) | Moderator, PlatformAdmin |
| GET | `/flags/{id}` | Get a flag | Moderator, PlatformAdmin |
| POST | `/flags/{id}/uphold` | Uphold a flag | Moderator |
| POST | `/flags/{id}/dismiss` | Dismiss a flag | Moderator |
| POST | `/saved-searches` | Save a search | Member |
| GET | `/saved-searches` | List saved searches | Member, PlatformAdmin |
| GET | `/saved-searches/{id}` | Get a saved search | Member, PlatformAdmin |
| GET | `/saved-searches/{id}/alerts` | List alerts for a saved search | Member, PlatformAdmin |
| POST | `/_clock/set` | Set the clock (no sweeps) | PlatformAdmin |
| POST | `/_clock/advance` | Advance the clock and run sweeps | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_LISTING_VERSION` | 412 |
| `ERR_STALE_OFFER_VERSION` | 412 |
| `ERR_MEMBER_NOT_ACTIVE` | 403 |
| `ERR_SPOT_NOT_POLICE_VERIFIED` | 422 |
| `ERR_SELLER_NOT_PHONE_VERIFIED` | 422 |
| `ERR_OUTSIDE_SPOT_HOURS` | 422 |
| `ERR_SPOT_TIME_CONFLICT` | 409 |
| `ERR_NOT_YOUR_TURN` | 409 |
| `ERR_MAX_ROUNDS_REACHED` | 409 |
| `ERR_ACTIVE_LISTING_LIMIT` | 409 |
| `ERR_MAX_RENEWALS_REACHED` | 409 |
| `ERR_PRICE_EXCEEDS_CATEGORY_CAP` | 422 |
| `ERR_NOT_CONVERSATION_PARTICIPANT` | 403 |
| `ERR_CANNOT_TRADE_OWN_LISTING` | 422 |
| `ERR_FLOOR_ABOVE_ASK` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_BAN_THRESHOLD_NOT_MET` | 409 |
| `ERR_VERIFICATION_CODE_MISMATCH` | 422 |

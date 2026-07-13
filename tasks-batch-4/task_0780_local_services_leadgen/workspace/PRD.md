# Local-Services Leadgen API — Product Requirements Document

## 1. Introduction

This document specifies the Local-Services Lead-Generation and Quote Marketplace API, a two-sided platform in the spirit of Thumbtack or Angi. On one side, customers describe a job — a category, a location, a budget, and free-text details — and expect to be matched with qualified professionals. On the other side, service professionals ("pros") pay to receive those job leads, either per lead or through a subscription, then negotiate quotes, book appointments, complete work, and accumulate a public reputation.

The platform's revenue and fairness both hinge on how a finite pool of leads is distributed. A single job request is metered out to at most a capped number of pros, one pro per distribution call, and each distribution charges the receiving pro against a prepaid wallet or a subscription credit balance. Because lead pricing rises with demand, because a pro's eligibility depends on verification standing and reputation, and because charges can be refunded or disputed under a lead guarantee, the system must treat billing state and contact/conversion state as two independent dimensions of the same lead and keep both perfectly consistent as bookings, cancellations, reviews, and dispute resolutions cascade through the graph.

The remainder of this document defines the global contract every endpoint honors (Section 2) and the domain workflows that give the platform its behavior (Section 3), followed by the endpoint and error-code reference tables (Sections 4 and 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. The platform recognizes exactly four roles: `Customer`, `Pro`, `PlatformAdmin`, and `CustomerService`. If either header is missing or the role is not one of these four, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

Two of the roles are backed by persisted entities, and two are opaque operator identities:

- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`. Ownership checks on any resource that references a customer — a `ServiceRequest`, a `Quote`, a `Booking`, or a `Review` — compare that resource's customer foreign key to `X-User-ID`.
- When `X-User-Role` is `Pro`, `X-User-ID` is the `id` of the acting `Pro`. Ownership checks on any resource that references a pro — a `Lead`, a `Quote`, a `Booking`, an `AvailabilitySlot`, a `Dispute`, or the `Pro` profile itself — compare that resource's pro foreign key to `X-User-ID`.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- When `X-User-Role` is `CustomerService`, `X-User-ID` is likewise an opaque operator identifier. The server may record it — specifically, taking a dispute under review writes the operator's `X-User-ID` into `assigned_cs_user_id` on the `Dispute` — but never compares it to any entity's `id`.

When an entity-backed actor is authenticated and permitted for the operation as a class, but is not the owner of the specific targeted resource, the request is rejected with `ERR_NOT_RESOURCE_OWNER`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object.

Beyond `limit` and `offset`, list endpoints accept domain filters that narrow the collection by exact match on the named fields. Pros may be filtered by `subscription_plan_id`, `category_id`, `zip_code`, and `verification_status`; service requests by `customer_id`, `category_id`, and `status`; leads by `request_id`, `pro_id`, `contact_status`, and `billing_status`; quotes by `lead_id`, `pro_id`, `customer_id`, and `status`; bookings by `quote_id`, `customer_id`, `pro_id`, and `status`; reviews by `booking_id`, `customer_id`, and `pro_id`; disputes by `lead_id`, `raised_by_pro_id`, and `status`; and availability slots by `pro_id`, `booking_id`, and `status`.

### 2.4. Common Resource Properties

Most resources — `Customer`, `Pro`, `ServiceRequest`, `Lead`, `Quote`, `Booking`, `Review`, `Dispute`, and `AvailabilitySlot` — carry a standard set of system-managed fields:

- `id` — a unique, server-minted UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits marking creation.
- `updated_at` — an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` — an integer that starts at its initial value and increments by one on every mutation. It is the anchor for optimistic concurrency control (Section 2.8).

Two configuration resources are immutable reference data and therefore carry only `id` and `created_at`: a `ServiceCategory` and a `SubscriptionPlan` have neither an `updated_at` nor a `version` field. Wherever this document speaks of "bumping the version" or "refreshing `updated_at`," it refers only to the nine versioned resources above; the two configuration resources are never mutated after creation.

### 2.5. Monetary Amounts, Ratings, and Rounding

All money is expressed in integer cents. Whenever a monetary result is produced by multiplication — a demand-adjusted lead price, a commission, or a processing fee — the raw product is rounded to a whole number of cents using the round-half-up convention (a fractional part of exactly one-half rounds away from zero, upward). Wallet balances (`credit_balance_cents`), credit counters (`remaining_lead_credits`), lead charges (`charge_cents`), refund amounts (`refund_cents`), and payouts (`payout_cents`) are always whole-cent integers.

Ratings are decimal numbers carried to two decimal places, also using round-half-up. A pro's published `rating_avg` and its internal `provisional_rating` are each `0.0` when their respective review sets are empty. Star ratings supplied by customers on a `Review` are integers.

### 2.6. The Logical Clock

The server never reads the real wall clock. Instead it keeps a logical clock whose value defaults, at process startup, to `2026-03-01T00:00:00Z`. A `PlatformAdmin` may advance or set this clock by supplying a target instant as `to_iso8601`; this is a test-driving capability with no domain side effects other than moving the clock. Every timestamp the system reads for business rules — the `distributed_at` stamped on a new lead, the "now" used to evaluate a refund window, the "now" compared against a booking's `scheduled_start` at completion, and the `created_at`/`updated_at` written on resources — is drawn from this logical clock.

### 2.7. Cascading State Consistency

Many operations mutate more than one resource in a single request, and the platform resolves every such cascade synchronously before returning. When a booking is created, for example, the accepted quote, the winning lead, the losing sibling leads, the service request, and the booked slot all change state within that one call. Each resource a cascade touches independently refreshes its `updated_at` and increments its `version` (for the two version-less configuration resources this does not apply, since they are never cascade targets). The detailed cascade chains live in the Section 3 workflow narratives; the governing principle here is that the platform never leaves a partially-applied cascade — either every dependent effect of an operation lands, or the operation is rejected before any effect is applied.

### 2.8. Optimistic Concurrency Control on Lead Distribution

Lead distribution is the one operation guarded by optimistic concurrency control. Distributing a service request advances that request's `version` (a new lead is created and its `distributed_lead_count` rises), so a client that distributes twice must observe the new version between calls. To enforce this, a distribute request must carry `expected_service_request_version` as a required field, holding the client's last observed `version` of the target `ServiceRequest`. If that value does not equal the request's current `version` — because another distribution has already advanced it since the client last read the request — the call is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a caller working from a stale view from distributing a lead against a request that a prior, superseding distribution has already progressed, which would double-charge pros. No other endpoint takes a version field; distribution is the sole OCC-guarded write.

### 2.9. Validation Order and Resource Resolution

When several conditions could reject a request, the platform evaluates them in a fixed priority order and returns the first failure. The order, from highest priority to lowest, is:

1. Authentication — both `X-User-ID` and `X-User-Role` present and the role recognized, else `ERR_UNAUTHENTICATED` (401).
2. Role permission — the role may perform this operation, else `ERR_FORBIDDEN_ROLE` (403).
3. Ownership — for owner-scoped writes, the entity-backed actor owns the targeted resource, else `ERR_NOT_RESOURCE_OWNER` (403).
4. Existence — every resource named in the path or body exists, validated left-to-right so the first missing reference determines the error, else `ERR_NOT_FOUND` (404).
5. State — the target resource is in a state that permits the requested transition, else `ERR_INVALID_STATE` (409).
6. Referential coherence — cross-referenced resources cohere (see the endpoints that carry this rule), else `ERR_REFERENCE_MISMATCH` (409).
7. Pro verification — when booking, the quote's pro is `VERIFIED`, else `ERR_PRO_NOT_VERIFIED` (409).
8. Eligible-pro availability — when distributing, the candidate set is non-empty, else `ERR_NO_ELIGIBLE_PROS` (409).
9. Refund window — a refund request falls inside the category's refund window, else `ERR_REFUND_WINDOW_CLOSED` (409).
10. Slot overlap — a new availability slot does not overlap an existing slot of the same pro, else `ERR_SLOT_OVERLAP` (409).
11. Booking conflict — a booking fits its slot and honors the travel buffer, else `ERR_BOOKING_CONFLICT` (409).
12. Funding — when distributing, at least one candidate pro can fund the lead, else `ERR_INSUFFICIENT_CREDIT` (402).
13. Field validity — enums, ranges, and interval fields are within their declared bounds, else `ERR_INVALID_REQUEST` (422).
14. Review uniqueness — at most one review per booking, else `ERR_DUPLICATE_REVIEW` (409).
15. Concurrency — the distribute request's `expected_service_request_version` matches, else `ERR_STALE_VERSION` (412).

The left-to-right existence rule (priority 4) means that when a body references several resources, the system resolves them in the order they are named and reports the first one that does not exist. Note that on distribution the eligibility check (priority 8) precedes the funding check (priority 12), which in turn precedes the field-validity and concurrency checks — so a request with no eligible pros surfaces `ERR_NO_ELIGIBLE_PROS` even if its version is also stale.

### 2.10. The Lead-Credit Ledger and Fiscal Conservation

Each pro holds two independent balances that together fund lead charges: a prepaid wallet, `credit_balance_cents`, and a subscription counter, `remaining_lead_credits`. Both are non-negative integers. The wallet is topped up by an operator, debited when a pay-per-lead or overage charge lands, and credited back when a charge is refunded. The subscription counter is granted when a pro subscribes, decremented when a subscription lead consumes one included credit, and restored when such a lead is refunded.

Two conservation invariants govern refunds. When a charged lead is refunded — whether by the pro's self-serve request or by a dispute resolved in the pro's favor — the pro's wallet is credited by exactly that lead's `charge_cents` (pro-credit conservation). Separately, if that lead had consumed a subscription credit (its `credits_consumed` is 1), the pro's `remaining_lead_credits` is incremented by one (subscription-credit conservation). A lead therefore never returns more value than it took, and never less.

## 3. Business Logic & Workflows

### 3.1. Onboarding Pros and the Verification Lifecycle

A `PlatformAdmin` registers a professional by supplying an `email` and a `business_name`, optionally a `phone`, an initial `billing_mode`, a list of `service_zip_codes`, and a list of `covered_category_ids`. A newly registered pro starts with `verification_status` of `UNVERIFIED` and `billing_mode` of `PAY_PER_LEAD`; its `subscription_plan_id` is null, its wallet `credit_balance_cents` and `remaining_lead_credits` are zero, and its reputation fields `rating_avg`, `rating_count`, `provisional_rating`, and `dispute_count` all begin at zero. Customers are registered the same way by an admin, each with an `email`, a `full_name`, and an optional `phone`; the `email` on both customers and pros must be unique and non-empty.

Verification is a four-state machine on `verification_status`. The owning pro submits its own profile for review, moving it from `UNVERIFIED` to `PENDING`; this transition is permitted only to the pro that owns the profile and bumps the pro's `version`. A `PlatformAdmin` then renders a decision by supplying `decision`. A decision of `APPROVE` moves a `PENDING` pro to `VERIFIED`; a decision of `SUSPEND` moves either a `PENDING` or an already-`VERIFIED` pro to `SUSPENDED`. Each of these admin transitions bumps the pro's `version`. Attempting to verify a pro that is not in a state permitting the decision is an `ERR_INVALID_STATE`; supplying a `decision` outside the allowed set is rejected with `ERR_VALIDATION_DECISION`.

An operator funds a pro's wallet with a top-up, supplying `amount_cents`, which is added to `credit_balance_cents` and bumps the pro's `version`. A pro may instead move to subscription billing by subscribing to a plan, supplying the `subscription_plan_id` of an existing `SubscriptionPlan`. Subscribing records that plan on the pro, sets `billing_mode` to `SUBSCRIPTION`, adds the plan's `included_lead_credits` to `remaining_lead_credits`, and bumps the pro's `version`. If the supplied plan does not exist, or the pro is already on that plan, the request is rejected with `ERR_SUBSCRIPTION_REQUIRED`.

### 3.2. Catalog Configuration: Categories and Plans

Before any matching can happen, a `PlatformAdmin` configures the catalog. A `ServiceCategory` is created with a unique, non-empty `name`, a `base_lead_price_cents` that must be greater than zero, a `max_leads_per_request` of at least one, a `demand_high_threshold` of at least zero, a `demand_multiplier_high` of at least 1.0, a `refund_window_hours` of at least zero, and a `min_rating_to_receive_leads` between 0.0 and 5.0 inclusive. These seven parameters together drive lead pricing, the distribution cap, the refund window, and reputation eligibility for that category.

A `SubscriptionPlan` is created with a unique, non-empty `tier` label, a `monthly_fee_cents` greater than zero, an `included_lead_credits` count of at least zero granted per cycle, and an `overage_price_cents` greater than zero charged to the wallet once included credits run out. Both categories and plans are immutable reference data once created.

### 3.3. Service Requests and the Lead Distribution Engine

A `Customer` opens a job by creating a `ServiceRequest` with their own `customer_id`, the `category_id` of the desired service, the job's `zip_code`, a free-text `description`, and a `budget_cents` of at least zero. The request begins in status `OPEN` with a `distributed_lead_count` of zero.

Distribution is the heart of the platform, and it is deliberately metered: each distribute call grants the lead to exactly one pro — the single best-matching pro not already holding a lead for this request — and the operator repeats the call to reach additional pros, up to the category's cap. A distribute call is available only to a `PlatformAdmin` and carries `expected_service_request_version` (Section 2.8). The first successful distribution moves the request from `OPEN` to `DISTRIBUTED`; subsequent distributions are a self-loop that keeps the request in `DISTRIBUTED` while adding one more lead each time. A distribution is permitted only while the request is `OPEN` or `DISTRIBUTED`, only while `distributed_lead_count` is strictly below the category's `max_leads_per_request`, and only when at least one pro qualifies.

**Selecting the pro.** The candidate set for a request consists of every pro that is `VERIFIED`, that lists the request's category in its `covered_category_ids`, that lists the request's `zip_code` in its `service_zip_codes`, that is not already holding a lead for this request, and whose reputation clears the category floor. The reputation floor is that the pro's `provisional_rating` is at least the category's `min_rating_to_receive_leads`; a pro whose `rating_count` is zero is exempt from this floor and always clears it. From the candidate set the system selects the single top-ranked pro, ranking by `provisional_rating` in descending order and breaking ties by the earlier `created_at` (ascending). If the candidate set is empty — because the cap has already been reached or because no pro satisfies the category, geography, reputation, and not-already-holding conditions — the distribution is rejected with `ERR_NO_ELIGIBLE_PROS`. Additionally, at least one candidate must be able to fund the lead (per the charge rules below); if the qualifying pros exist but none can fund the charge, the distribution is rejected with `ERR_INSUFFICIENT_CREDIT`.

**Charging the lead.** When the selected pro is charged, the system first measures current demand for the category. It counts the existing leads in the same category whose `contact_status` is `DISTRIBUTED`, `CONTACTED`, or `QUOTED` and whose `created_at` is strictly earlier than the current logical-clock instant; converted, closed, and this brand-new lead are excluded from the count. If that open-lead count is greater than or equal to the category's `demand_high_threshold`, the demand multiplier is the category's `demand_multiplier_high`; otherwise the multiplier is 1.0. The gross price in cents is the category's `base_lead_price_cents` multiplied by that multiplier, rounded half-up to a whole cent.

How the gross price is settled depends on the pro's `billing_mode`, which is snapshotted onto the new lead. For a `PAY_PER_LEAD` pro, `charge_cents` is the gross price, `credits_consumed` is 0, and `credit_balance_cents` is debited by that amount (a pro qualifies for funding only when the wallet already covers the gross price). For a `SUBSCRIPTION` pro, if `remaining_lead_credits` is at least one, `charge_cents` is 0, `credits_consumed` is 1, and one credit is decremented from `remaining_lead_credits`; otherwise the pro pays overage, where `charge_cents` becomes the plan's `overage_price_cents`, `credits_consumed` is 0, and the wallet is debited by that overage. A subscription pro can therefore fund a lead either by holding a credit or by holding wallet balance for the overage.

Each successful distribution creates one `Lead` recording its `request_id`, `pro_id`, a `category_id` snapshot from the request, the `billing_mode` snapshot, the computed `charge_cents` and `credits_consumed`, an initial `contact_status` of `DISTRIBUTED`, an initial `billing_status` of `CHARGED`, and a `distributed_at` stamped from the logical clock. The request's `distributed_lead_count` rises by one and its `version` is bumped.

A customer may close their own `OPEN` or `DISTRIBUTED` request. Closing sets the request's status to `CLOSED` (a terminal state), and — when the request was `DISTRIBUTED` — every lead of that request still in an open contact stage (`DISTRIBUTED`, `CONTACTED`, or `QUOTED`) is moved to `CLOSED`. Closing does not by itself alter billing state; a charged lead remains charged unless separately refunded or disputed.

### 3.4. Working a Lead: Contact, Quotes, and Negotiation

A lead carries two independent state dimensions on the same row: a `contact_status` tracking conversation and conversion, and a `billing_status` tracking money. They evolve separately, and this subsection concerns the contact dimension; the billing dimension is covered in Section 3.7.

The pro who owns a lead marks it contacted, advancing `contact_status` from `DISTRIBUTED` to `CONTACTED`; this is permitted only to the owning pro and only from `DISTRIBUTED`. To make an offer, the pro sends a quote, supplying the `lead_id`, an `amount_cents` greater than zero, a `message`, and optionally a `valid_until` expiry. Creating the quote copies the lead's pro onto the quote as `pro_id` and the lead's requesting customer as `customer_id`, sets the quote's `status` to `SENT` with a `revision_count` of zero, and cascades the lead's `contact_status` from `CONTACTED` to `QUOTED`. A quote may only answer a lead that belongs to the acting pro; if the quote's lead does not belong to the pro raising it, the request is rejected with `ERR_REFERENCE_MISMATCH`.

Quotes negotiate through a revision loop. A customer who owns a `SENT` quote may request a revision, moving it to `REVISION_REQUESTED` and incrementing `revision_count`. The owning pro then re-sends a revised quote, supplying a new `amount_cents`; this moves the quote from `REVISION_REQUESTED` back to `SENT` and updates the stored `amount_cents`. The pair `SENT → REVISION_REQUESTED → SENT` may repeat any number of times. A quote leaves this loop only by being accepted, which happens as a system cascade when the customer books it (Section 3.5): a `SENT` quote transitions to `ACCEPTED`, its terminal state.

### 3.5. Booking, Scheduling, and the Calendar

A pro publishes availability by creating an `AvailabilitySlot` with its own `pro_id`, a `start_utc`, and an `end_utc` that must be strictly after `start_utc`. A slot begins `OPEN` with a null `booking_id`. Slots are treated as half-open intervals `[start_utc, end_utc)`: a new slot may share an exact endpoint with an existing slot of the same pro (touching is allowed), but any true overlap with another slot of that pro is rejected with `ERR_SLOT_OVERLAP`.

A `Customer` books an accepted offer by creating a `Booking` with the `quote_id` being accepted, the `availability_slot_id` to reserve, a `scheduled_start`, and a `scheduled_end` that must be strictly after `scheduled_start`. Booking is the platform's largest cascade and is subject to several checks. Referential coherence requires that the slot belong to the same pro as the quote; a mismatch yields `ERR_REFERENCE_MISMATCH`. The quote's pro must be `VERIFIED`, or the booking is rejected with `ERR_PRO_NOT_VERIFIED`. The appointment window must satisfy the calendar rule below, or the booking is rejected with `ERR_BOOKING_CONFLICT`.

**The calendar rule.** The booking window `[scheduled_start, scheduled_end]` must fit entirely inside the referenced `OPEN` slot's interval `[start_utc, end_utc]`. In addition, it must stay clear of every other `CONFIRMED` booking of the same pro by at least a thirty-minute travel buffer: treat each existing confirmed booking's window as a closed interval, expand it by thirty minutes on both the leading and trailing side, and reject the new booking if it intersects any such expanded interval. Only when the window fits its slot and clears the buffer against all other confirmed bookings does the booking proceed.

A successful booking copies the quote's pro onto the booking as `pro_id`, the quote's customer as `customer_id`, and the quote's `amount_cents` onto the booking as `price_cents`; its `payout_cents` starts at zero and its `status` starts at `CONFIRMED`. The creation then drives a chain of cascades, all resolved within the one request: the accepted quote moves `SENT → ACCEPTED`; the quote's lead moves `contact_status` `QUOTED → CONVERTED`; every sibling lead of the same request still in an open contact stage (`DISTRIBUTED`, `CONTACTED`, or `QUOTED`) is moved to `CLOSED`; the service request moves to `BOOKED`; and the reserved slot moves `OPEN → BOOKED` with its `booking_id` set to the new booking. Each touched resource refreshes `updated_at` and bumps `version`.

Either party to a booking — its customer or its pro — may cancel a `CONFIRMED` booking, optionally supplying a `cancellation_reason`. Cancellation sets the booking's `status` to `CANCELLED` and, as compensation, returns the referenced slot from `BOOKED` back to `OPEN` and clears its `booking_id` to null, so the pro's calendar minute is freed for reuse.

### 3.6. Completion, Payout, and Reputation

The owning pro completes a `CONFIRMED` booking once the appointment has begun — that is, the completion is permitted only when the logical clock is at or after the booking's `scheduled_start`. Completion moves the booking to `COMPLETED` and computes the pro's `payout_cents` from the booking's `price_cents`. The payout is computed in a pinned order: first the commission is the price multiplied by fifteen percent, rounded half-up to a whole cent on its own; second the processing fee is the price multiplied by two-point-nine percent plus a flat thirty cents, also rounded half-up to a whole cent on its own; third the payout is the price minus the already-rounded commission minus the already-rounded processing fee. The two fees are always rounded independently before they are subtracted; the price is never multiplied by the combined percentage.

After a completed booking, the customer who owns it may leave one `Review`, supplying the `booking_id`, an integer `rating` from 1 to 5 inclusive, and an optional `text` body. The review copies the booking's customer and pro as `customer_id` and `pro_id`, and begins in moderation status `PENDING`. A review may only be written against a booking that belongs to the acting customer, or the request is rejected with `ERR_REFERENCE_MISMATCH`; at most one review may exist per booking, and a second attempt is rejected with `ERR_DUPLICATE_REVIEW`. A `rating` outside the integer range 1 through 5 is rejected with `ERR_INVALID_REQUEST`; note that the range check is applied before the per-booking uniqueness check.

Reputation is maintained as two variants of the same average. A pro's public reputation, `rating_avg`, is the mean `rating` over that pro's `PUBLISHED` reviews, rounded half-up to two decimals, with `rating_count` being the number of such published reviews; when the pro has no published reviews both are their zero defaults. A pro's internal `provisional_rating` — the value the distribution engine gates on — is the mean `rating` over that pro's reviews whose status is `PENDING` or `PUBLISHED`, also rounded half-up to two decimals, and `0.0` when that set is empty. Creating a review recomputes the pro's `provisional_rating` immediately, so a fresh, still-unmoderated low rating can drag a pro's eligibility before a moderator ever sees it. A `PlatformAdmin` or `CustomerService` moderator publishes a `PENDING` review, moving it to `PUBLISHED` and recomputing all three of `rating_avg`, `rating_count`, and `provisional_rating` for the pro.

### 3.7. Refunds, Disputes, and the Lead Guarantee

The billing dimension of a lead — its `billing_status` — starts at `CHARGED` and evolves on its own timeline, independent of contact progress. There are two routes back to a refunded charge: a pro's self-serve refund inside the category window, and a dispute adjudicated under the lead guarantee.

**Self-serve refund.** The pro who owns a `CHARGED` lead may request a refund, optionally supplying a `reason`. This is allowed only while the logical clock is strictly earlier than the lead's `distributed_at` plus the category's `refund_window_hours`; a request at or after that deadline is rejected with `ERR_REFUND_WINDOW_CLOSED`. Within the window, the lead's `billing_status` moves to `REFUNDED`, the pro's wallet is credited by the lead's `charge_cents`, and — if the lead had consumed a subscription credit — one credit is restored to `remaining_lead_credits`. The refund bumps the pro's `version`.

**Disputes.** Alternatively, the owning pro raises a `Dispute` against a lead under the guarantee, supplying the `lead_id` and a `reason` (for example a wrong number, a duplicate, or an out-of-area lead). A dispute may only be raised on a lead whose `billing_status` is `CHARGED`; otherwise it is rejected with `ERR_DISPUTE_NOT_ALLOWED`. Raising the dispute records the pro as `raised_by_pro_id`, starts the dispute in status `OPEN` with `refund_cents` of zero and a null `resolution_note`, and cascades the lead's `billing_status` from `CHARGED` to `DISPUTED`.

A `CustomerService` operator takes an `OPEN` dispute under review, moving it to `UNDER_REVIEW` and writing that operator's identity into `assigned_cs_user_id`. The same role then resolves an `UNDER_REVIEW` dispute by supplying a `decision`, optionally with a `resolution_note`. A decision of `REFUND` requires the disputed lead's `billing_status` to still be `DISPUTED`; it moves the dispute to `RESOLVED_REFUNDED`, sets the dispute's `refund_cents` to the disputed lead's `charge_cents`, and cascades the lead's `billing_status` from `DISPUTED` back to `REFUNDED` — crediting the pro's wallet by that `charge_cents` and restoring one subscription credit to `remaining_lead_credits` if the lead had consumed one. A decision of `DENY` moves the dispute to `RESOLVED_DENIED`, leaves `refund_cents` at zero, reverts the lead's `billing_status` from `DISPUTED` back to `CHARGED`, and increments the pro's `dispute_count` by one. Both `RESOLVED_REFUNDED` and `RESOLVED_DENIED` are terminal. A `decision` outside the allowed set is rejected with `ERR_VALIDATION_DECISION`.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return `201 Created`. Operations that modify an existing resource — including all state transitions, verification decisions, top-ups, subscriptions, distribution, and dispute handling — return `200 OK`. The request and response bodies for each endpoint are described in the Section 3 narratives; the table below fixes only the method, path, purpose, and authorized roles.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Register a customer | PlatformAdmin |
| GET | `/customers/{id}` | Fetch a customer | Customer, PlatformAdmin, CustomerService |
| POST | `/pros` | Register a pro | PlatformAdmin |
| GET | `/pros/{id}` | Fetch a pro profile | Pro, Customer, PlatformAdmin, CustomerService |
| GET | `/pros` | List/match pros with filters | PlatformAdmin, Customer |
| POST | `/pros/{id}/submit-verification` | Pro submits profile for verification | Pro |
| POST | `/pros/{id}/verify` | Admin approves or suspends a pro | PlatformAdmin |
| POST | `/pros/{id}/credit-topup` | Add prepaid lead credit to a pro wallet | PlatformAdmin |
| POST | `/pros/{id}/subscribe` | Pro subscribes to a plan | Pro |
| POST | `/service-categories` | Create a service category | PlatformAdmin |
| GET | `/service-categories/{id}` | Fetch a category | PlatformAdmin, Customer, Pro, CustomerService |
| POST | `/subscription-plans` | Create a subscription plan | PlatformAdmin |
| GET | `/subscription-plans/{id}` | Fetch a plan | PlatformAdmin, Pro |
| POST | `/service-requests` | Customer creates a service request | Customer |
| GET | `/service-requests/{id}` | Fetch a request | Customer, Pro, PlatformAdmin, CustomerService |
| GET | `/service-requests` | List requests with filters | Customer, PlatformAdmin |
| POST | `/service-requests/{id}/distribute` | Grant the lead to the top-ranked eligible pro (OCC-guarded) | PlatformAdmin |
| POST | `/service-requests/{id}/close` | Customer closes a request | Customer |
| GET | `/leads/{id}` | Fetch a lead | Pro, Customer, PlatformAdmin, CustomerService |
| GET | `/leads` | List leads with filters | Pro, PlatformAdmin, Customer |
| POST | `/leads/{id}/contact` | Pro marks a lead contacted | Pro |
| POST | `/leads/{id}/refund-request` | Pro self-serves a lead refund within the window | Pro |
| POST | `/quotes` | Pro sends a quote for a lead | Pro |
| GET | `/quotes/{id}` | Fetch a quote | Customer, Pro, PlatformAdmin |
| GET | `/quotes` | List quotes with filters | Customer, Pro, PlatformAdmin |
| POST | `/quotes/{id}/send` | Pro (re)sends a revised quote | Pro |
| POST | `/quotes/{id}/request-revision` | Customer requests a quote revision | Customer |
| POST | `/bookings` | Customer books an accepted quote onto a slot | Customer |
| GET | `/bookings/{id}` | Fetch a booking | Customer, Pro, PlatformAdmin |
| GET | `/bookings` | List bookings with filters | Customer, Pro, PlatformAdmin |
| POST | `/bookings/{id}/complete` | Pro marks a booking completed; computes payout | Pro |
| POST | `/bookings/{id}/cancel` | Customer or pro cancels a booking; frees the slot | Customer, Pro |
| POST | `/reviews` | Customer reviews a completed booking | Customer |
| GET | `/reviews/{id}` | Fetch a review | Customer, Pro, PlatformAdmin, CustomerService |
| GET | `/reviews` | List reviews with filters | Customer, Pro, PlatformAdmin, CustomerService |
| POST | `/reviews/{id}/publish` | Moderator publishes a review; recomputes ratings | PlatformAdmin, CustomerService |
| POST | `/disputes` | Pro raises a lead-guarantee dispute | Pro |
| GET | `/disputes/{id}` | Fetch a dispute | Pro, PlatformAdmin, CustomerService |
| GET | `/disputes` | List disputes with filters | Pro, PlatformAdmin, CustomerService |
| POST | `/disputes/{id}/review` | CS takes a dispute under review | CustomerService |
| POST | `/disputes/{id}/resolve` | CS resolves a dispute (refund or deny) | CustomerService |
| POST | `/availability-slots` | Pro creates a calendar slot (overlap-checked) | Pro |
| GET | `/availability-slots/{id}` | Fetch a slot | Pro, Customer, PlatformAdmin |
| GET | `/availability-slots` | List slots with filters | Pro, Customer, PlatformAdmin |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_REFERENCE_MISMATCH` | 409 |
| `ERR_PRO_NOT_VERIFIED` | 409 |
| `ERR_NO_ELIGIBLE_PROS` | 409 |
| `ERR_INSUFFICIENT_CREDIT` | 402 |
| `ERR_REFUND_WINDOW_CLOSED` | 409 |
| `ERR_SLOT_OVERLAP` | 409 |
| `ERR_BOOKING_CONFLICT` | 409 |
| `ERR_DUPLICATE_REVIEW` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_VALIDATION_DECISION` | 422 |
| `ERR_SUBSCRIPTION_REQUIRED` | 409 |
| `ERR_DISPUTE_NOT_ALLOWED` | 409 |

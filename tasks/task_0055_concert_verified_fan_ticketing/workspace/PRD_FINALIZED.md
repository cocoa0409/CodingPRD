# Concert Verified Fan Ticketing API — Product Requirements Document

## 1. Introduction

High-demand concert ticketing has long been distorted by automated buying rings, scalper resale at predatory markups, and queue-jumping that pushes genuine fans out of the market. This API exists to give a promoter a single, trustworthy sales channel that puts verified human fans first. It governs the full journey from fan registration and bot screening, through a presale-gated virtual queue, dynamic demand-based pricing, a strictly capped resale market, and finally mobile-only gate entry at the venue.

The platform is organized around eight peer resources — fans, events, price tiers, queue entries, orders, tickets, transfers, and resale listings — bound together by foreign keys rather than nested URL hierarchies. Each event publishes a finite seat allocation across one or more price tiers; fans compete for those seats through a position-ordered virtual queue that the promoter advances in waves. Seats move through a careful ledger of reservations and commitments so that the venue is never oversold and every released seat returns to the pool for the next waiting fan. Around that core, a bot-risk scoring model, a verified-fan gate, a transfer protocol, and a price-capped resale market enforce the fairness guarantees that give the channel its value.

Because money, scarce inventory, and concurrent buyers all intersect here, the system treats consistency as non-negotiable: every mutation is immediately visible, every derived counter is kept in lockstep with the state machines that drive it, and guarded writes are protected against acting on stale data. The sections below specify the global contracts first, then the business workflows that an engineer must implement to satisfy them.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the operational capacity under which the request is made. The system recognizes exactly four roles, spelled precisely as `Anonymous`, `Fan`, `PromoterAdmin`, and `GateScanner`. A request that omits either header, or that names a role outside this set, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is recognized but is not permitted to perform the targeted operation is rejected with `ERR_FORBIDDEN_ROLE`.

The four roles differ in how `X-User-ID` binds to persisted data. When `X-User-Role` is `Fan`, `X-User-ID` is the `id` of the acting `Fan`; ownership checks on any resource that references a `Fan` compare the resource's relevant foreign-key field — for example an order's `fan_id`, a ticket's `holder_fan_id`, a listing's `seller_fan_id`, or a transfer's sender or recipient — against `X-User-ID`. When `X-User-Role` is `Anonymous`, `PromoterAdmin`, or `GateScanner`, `X-User-ID` is an opaque operational identifier not tied to any persisted entity. The server may record such an identifier for audit but never compares it to any entity's `id`. `Anonymous` may register a new fan and browse the public catalog (events, price tiers, individual fans, and open resale listings). `PromoterAdmin` operates events, pricing, queue advancement, and the test-driving clock, and may list all fans. `GateScanner` performs mobile-only entry scans and may read tickets.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and accepted values range from a minimum of 1 to a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific workflow says otherwise, list endpoints return resources sorted by their creation timestamp in ascending order. The `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in the system — `Fan`, `Event`, `PriceTier`, `QueueEntry`, `Order`, `Ticket`, `Transfer`, and `ResaleListing` — carries a system-managed `id`: a UUID minted by the server with no type prefix. The `id` is identity only and is never an input to any business decision. Resources are first created with a `created_at` timestamp, an ISO 8601 UTC value rendered with three fractional digits, and an `updated_at` timestamp of the same format that is refreshed on every subsequent modification.

Each resource also carries a `version`, an integer that begins at 1 at creation and increments by exactly 1 on every mutation, including mutations that arrive indirectly as a cascade from another operation. The `version` is the basis for optimistic concurrency control described in §2.7. Whenever a derived counter on a resource changes — for instance a tier's `reserved_count` or `sold_count`, an event's `tickets_sold_count`, or a fan's `completed_purchase_count` — that change is itself a mutation that refreshes `updated_at` and increments `version` on the affected resource.

### 2.5. Demand Pricing, Fees, and Refund Precision

All money in the system is stored and returned as an integer count of cents. Wherever a calculation in §3 calls for rounding, the rounding method is **round half up**, applied at exactly the step the workflow names and never re-applied to an already-rounded subtotal. Demand-based pricing, the per-order service fee, the loyalty-tiered refund, and the resale price cap are all computed in integer cents with round-half-up at their pinned steps. The pricing engine never permits a per-seat price below the event's face value: after demand and tier adjustments, the locked unit price is taken as the larger of the computed value and `face_value_cents`.

### 2.6. Seat-Ledger Consistency and Cascades

Seat inventory is the system's most carefully guarded invariant. Each `PriceTier` exposes a finite `allocation` and two derived counters — `reserved_count`, the seats currently held by live offers, and `sold_count`, the seats committed by paid orders. A tier's occupancy at any moment is `reserved_count + sold_count`, and the tier's remaining capacity is its `allocation` minus that occupancy. Reservations and commitments move through these counters in lockstep with the queue and order state machines: offering a waiting entry raises `reserved_count`; letting an offer expire or revoking it lowers `reserved_count`; paying an order moves the seats from reserved to sold; and refunding an order returns sold seats to the pool. Each such counter change increments the affected tier's `version`.

Several operations ripple beyond the resource they target, and the system applies every cascade atomically and immediately. Paying an order, for example, not only marks the order and its queue entry but also adjusts tier counters, the event's running sales total, and the buyer's purchase count, and may in turn drive the event to a sold-out state that revokes other fans' waiting positions. Refunding compensates the same chain in reverse and can re-open an event for sales. Flagging a previously verified fan revokes that fan's live queue holds. In each case the secondary effects are part of the same transaction as the primary one, and every touched resource has its `updated_at` refreshed and its `version` incremented.

### 2.7. Optimistic Concurrency Control

Certain mutating endpoints are guarded against acting on stale data by requiring the client to echo back the `version` of the parent resource it last observed. Paying an order requires an `expected_order_version` field carrying the client's last observed `version` of the target `Order`; if that value does not equal the order's current `version`, the payment is rejected with `ERR_STALE_VERSION` (HTTP 412), because an intervening mutation — a cancel attempt or a system offer-expiry cascade that touched the order — has advanced the order beyond what the payer observed. Buying a resale listing requires an `expected_resalelisting_version` field carrying the client's last observed `version` of the target `ResaleListing`; if that value does not equal the listing's current `version`, the purchase is rejected with `ERR_STALE_VERSION` (HTTP 412), because another buyer has already advanced the listing (for instance by completing the purchase first). The three event lifecycle transitions — opening presale, opening general sales, and closing — likewise require an `expected_event_version` matching the event's current `version`, and reject a mismatch with `ERR_STALE_VERSION` (HTTP 412). Endpoints that are not named here take no version field.

### 2.8. Resource Existence and Ownership Resolution

When a request references resources by path identifier or by body foreign key, the system confirms their existence before applying any business rule, validating referenced resources left-to-right in the natural dependency order (event, then tier, then fan, then queue entry, then order, then ticket, then transfer, then listing). The first referenced resource that does not exist causes the request to be rejected with `ERR_NOT_FOUND`. Only once all referenced resources are confirmed to exist does the system check that the acting `Fan` owns the resource being mutated; an attempt by a fan to act on another fan's order, ticket, listing, or transfer is rejected with `ERR_NOT_RESOURCE_OWNER`.

### 2.9. Validation Ordering

When several checks apply to a single operation, they are evaluated in a fixed priority order so that the earliest applicable failure is the one reported. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN_ROLE`), then existence of all referenced resources (`ERR_NOT_FOUND`), then ownership of the mutated resource (`ERR_NOT_RESOURCE_OWNER`), then whether the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`). Only after those five structural gates do the domain-specific business rules run, in this order: the bot-flag bar (`ERR_FAN_FLAGGED`), the presale-code gate (`ERR_INVALID_PRESALE_CODE`), the mobile-only entry gate (`ERR_NON_MOBILE_ENTRY`), the verified-fan restriction (`ERR_FAN_NOT_VERIFIED`), the self-dealing bar (`ERR_SELF_DEALING`), the resale price cap (`ERR_RESALE_CAP_EXCEEDED`), the order-quantity check (`ERR_QTY_MISMATCH`), the already-scanned refund bar (`ERR_TICKET_ALREADY_SCANNED`), the offer-expiry check (`ERR_OFFER_EXPIRED`), and the allocation cap (`ERR_ALLOCATION_EXCEEDED`). Required-field and well-typedness checks surface as `ERR_INVALID_REQUEST`, and the optimistic-concurrency check surfaces as `ERR_STALE_VERSION`. This ordering matters: a flagged actor, for instance, is always reported as `ERR_FAN_FLAGGED` rather than being masked by the later verified-fan check.

## 3. Business Logic & Workflows

### 3.1. Fan Registration and Bot Screening

A fan joins the platform by registering with an `email`, a `full_name`, and a `device_fingerprint`. The `email` is the login and contact address and must be unique across all fans and non-empty; `full_name` is the legal name printed on tickets for entry; and `device_fingerprint` is an opaque device hash captured at registration that the platform reuses to detect coordinated bot rings. Registration always lands the new fan in the `UNVERIFIED` verification state with a freshly computed `risk_score`, and a `completed_purchase_count` of 0.

The `risk_score` is a bot-detection score that lives on the fan in the range 0 to 100, recomputed at registration and again on every queue join. It is the sum of three contributions, clamped to a maximum of 100. The first is a device-sharing contribution: the system counts how many *other* fans (any fan whose `id` differs from this one) carry the same `device_fingerprint`, multiplies that count by 20 points per shared device, and caps the contribution at 60 points. The second is a velocity contribution: the system counts how many queue entries this fan created within the trailing one-hour window (3600 seconds, measured by `created_at`), *including* the queue entry being created by the current join, so that a fan's Nth rapid join sees a velocity of N when all prior joins fall inside the window; the first 2 such joins are free, each join beyond the second adds 15 points, and the contribution is capped at 30 points. Expressed precisely, the velocity points are 15 multiplied by the velocity count minus 2 (never less than zero), capped at 30. The third is an alias-email contribution: if the `email` contains a `+` character, 25 points are added, otherwise 0. The three contributions are summed and the result is clamped so the stored `risk_score` is never below 0 nor above 100.

The `verification_status` is a computed gate over the fan lifecycle, one of `UNVERIFIED`, `VERIFIED`, or `FLAGGED`, defaulting to `UNVERIFIED`. `UNVERIFIED` is a genuine resting state: such a fan is not bot-flagged but is also not yet cleared to participate. A fan submits to the verified-fan check while in `UNVERIFIED`; if the current `risk_score` is below the bot-flag threshold of 70, the fan transitions `UNVERIFIED → VERIFIED`. If the `risk_score` is at or above 70, the fan instead transitions `UNVERIFIED → FLAGGED`. `FLAGGED` is terminal: a flagged fan can never verify, join a queue, pay, initiate or accept a transfer, or list or buy on resale. Attempting the verified-fan check from any status other than `UNVERIFIED` is an undefined transition and is rejected with `ERR_INVALID_STATE`.

Bot screening does not stop at registration. Each time a verified fan joins a queue, the `risk_score` is recomputed, and if it has risen to 70 or above, the system transitions the fan `VERIFIED → FLAGGED` on the spot. This flagging cascades: every one of that fan's queue entries currently in `WAITING` or `OFFERED` is revoked to `REVOKED`, releasing any held seats back to the pool as described in §3.3. A fan's `verification_status`, `risk_score`, and `completed_purchase_count` are all server-computed; only `email`, `full_name`, and `device_fingerprint` are supplied at registration.

### 3.2. Event Setup and Sales Lifecycle

A `PromoterAdmin` creates an event in `DRAFT` by supplying a `title`, a `venue_capacity` (the total mobile-entry capacity, which must be greater than zero), a `presale_code` (a non-empty shared code), a `face_value_cents` base price (greater than zero), and optionally a `resale_cap_pct`. The `resale_cap_pct` is the maximum resale markup over face value expressed as a whole-number percent; it defaults to 110 and must be at least 100. The event also carries computed fields the promoter does not set directly: `tickets_sold_count` (the number of tickets issued for the event, starting at 0) and `sales_status`, the lifecycle gate, one of `DRAFT`, `PRESALE`, `GENERAL`, `SOLD_OUT`, or `CLOSED`, defaulting to `DRAFT`.

While the event is still in `DRAFT`, the promoter defines its seating by creating one or more price tiers, each supplied with the owning `event_id`, a `name` label such as FLOOR or MEZZANINE, an `allocation` (the finite seat pool for that tier, greater than zero), and a `base_multiplier_bps` (the tier's price multiplier over face value in basis points, where 10000 represents 1.0x and the value must be at least 10000). A tier also exposes the computed counters `reserved_count` and `sold_count`, both starting at 0. Price tiers may only be created while their event is in `DRAFT`.

The promoter walks the event through its sales phases. Opening presale advances the event `DRAFT → PRESALE`, and is permitted only when at least one price tier already exists for the event and the supplied `expected_event_version` matches; the transition sets `sales_status` to `PRESALE` and increments the event's `version`. Opening general sales advances `PRESALE → GENERAL` (again gated by `expected_event_version`), setting `sales_status` to `GENERAL`. During `PRESALE`, joining the queue demands a matching presale code; during `GENERAL`, no presale code is required. The promoter may close the event from either `SOLD_OUT` or `GENERAL`, advancing it to `CLOSED` (the terminal state) and incrementing `version`, again gated by `expected_event_version`. An event also reaches `SOLD_OUT` automatically — see §3.4.

### 3.3. The Virtual Queue and Seat Reservation

A verified fan enters the competition for seats by joining the virtual queue, supplying the `event_id`, their `fan_id`, the desired `tier_id`, the `presale_code_used`, and a `requested_qty` of seats between 1 and 6 inclusive (6 is the maximum any single fan may request). On join the entry is created in `WAITING` with a server-assigned `queue_position`: a 1-based admission rank ordered by join time (`created_at` ascending), where a lower position is admitted first; admission order follows `queue_position` ascending and never the entry's `id`. The join also recomputes the fan's `risk_score` and may trigger the flag cascade of §3.1. During `PRESALE`, the submitted `presale_code_used` must equal the event's `presale_code`, and a mismatch is rejected with `ERR_INVALID_PRESALE_CODE`; during `GENERAL` the code is not enforced. A queue entry's `status` is one of `WAITING`, `OFFERED`, `PURCHASED`, `EXPIRED`, or `REVOKED`, and it carries an `offer_expires_at` timestamp that is null until an offer is made.

The promoter releases seats to fans in waves by advancing the queue, optionally narrowing the wave to a single `tier_id` and optionally bounding the number of offers with `max_offers`. Advancing the queue does two things. First, it sweeps offers that have gone stale: any entry in `OFFERED` whose `offer_expires_at` has passed (the current time is strictly later than `offer_expires_at`) transitions `OFFERED → EXPIRED`, and its reserved seats are released — `reserved_count` is decremented by that entry's `requested_qty` and the tier's `version` is incremented — returning the seats to the finite pool for the next waiting entry. Second, it offers seats to the most senior admittable waiting entries: an entry transitions `WAITING → OFFERED` only when its event is in `PRESALE` or `GENERAL`, it holds the lowest `queue_position` among `WAITING` entries for its tier (by `created_at` ascending) whose `requested_qty` still fits, and the tier's remaining capacity — `allocation` minus the sum of `reserved_count` and `sold_count` — is at least the entry's `requested_qty`. On offer, the entry's `status` becomes `OFFERED`, its `offer_expires_at` is set to the offer time plus the offer window of 120 seconds, the tier's `reserved_count` is increased by the entry's `requested_qty`, and the tier's `version` is incremented. An offer that would push a tier's occupancy beyond its `allocation` is barred with `ERR_ALLOCATION_EXCEEDED`.

A fan with an active offer redeems it by placing an order, described in §3.4. If the fan never redeems and the window lapses, the next advance sweeps the entry to `EXPIRED` and frees its seats. Two cascades can also revoke a waiting position outright: when an event sells out, every `WAITING` entry for that event is moved to `REVOKED`; and when a fan is flagged, that fan's `WAITING` entries are moved to `REVOKED`. When a flagged fan's `OFFERED` entry is revoked, its held seats are released — `reserved_count` is decremented by the entry's `requested_qty` and the tier's `version` is incremented — exactly as an expiry would do, whereas revoking a merely `WAITING` entry releases nothing because no seats were reserved for it. `PURCHASED`, `EXPIRED`, and `REVOKED` are all terminal for a queue entry.

### 3.4. Ordering, Payment, and the Sold-Out Cascade

When a fan holds an `OFFERED` queue entry, they redeem it by creating an order that references the `queue_entry_id`, the purchasing `fan_id` (which must equal the queue entry's `fan_id`), the `tier_id` inherited from the entry, and a `quantity` of seats. The `quantity` must equal the redeemed entry's `requested_qty` and lie within 1 to 6; a violation is rejected with `ERR_QTY_MISMATCH`. Redeeming an entry whose `offer_expires_at` has already passed is rejected with `ERR_OFFER_EXPIRED`. The order is created in `PENDING` with `refund_amount_cents` of 0 and with its pricing locked at creation.

At order creation the system locks the per-seat price into `unit_price_cents`. It begins from the event's `face_value_cents` and applies the tier multiplier: the tier-priced base is the face value multiplied by the tier's `base_multiplier_bps` divided by 10000, rounded half up. It then determines a demand band from the event's sold ratio — `tickets_sold_count` divided by `venue_capacity`, snapshotted *before* this order commits its seats. When the sold ratio is below 0.50 the demand surcharge is 0 basis points; when it is at least 0.50 but below 0.80 the surcharge is 1500 basis points; and when it is at least 0.80 (including a ratio of 1.00 or more) the surcharge is 3000 basis points. The unit price is then the tier-priced base multiplied by the sum of 10000 and the demand basis points, divided by 10000, rounded half up. Finally the unit price is floored at face value, taking the larger of that result and `face_value_cents`. One presale variant overrides the demand band: if the event is in `PRESALE` at order creation, the demand surcharge is forced to 0 basis points regardless of the sold ratio, so presale buyers pay the tier price with no surcharge.

The order's money fields follow a pinned rounding order. The `subtotal_cents` is the locked `unit_price_cents` multiplied by `quantity`, computed exactly with no rounding. The `service_fee_cents` is the service fee applied to that summed subtotal — the subtotal multiplied by 1200 basis points divided by 10000, rounded half up once — never applied per seat. The `total_cents` is the subtotal plus the service fee.

A `PENDING` order is paid by the owning fan, who supplies `expected_order_version`; the order must be `PENDING`, its linked queue entry must still be `OFFERED` and not expired, and the version must match (otherwise `ERR_STALE_VERSION`). For payment, the `ERR_INVALID_STATE` structural state gate (§2.9) is evaluated against the target `Order` itself: an order that is not `PENDING` is rejected with `ERR_INVALID_STATE`. The state of the linked queue entry is then classified into two distinct failures: if the linked entry has *lapsed* — it has been swept to `EXPIRED`, or its `offer_expires_at` is in the past (current time strictly later than `offer_expires_at`) — that is the domain-specific offer-expiry rule and is reported as `ERR_OFFER_EXPIRED` (at its §2.9 priority, after the flag and verified-fan bars); but if the linked entry is missing or is non-`OFFERED` for any reason other than having lapsed, that is reported as `ERR_INVALID_STATE`. Payment is a depth-three cascade. The order moves `PENDING → PAID`; the linked queue entry moves to `PURCHASED`; the tier's seats move from reserved to sold (`reserved_count` decreased by `quantity`, `sold_count` increased by `quantity`); one ticket per seat is issued (`quantity` tickets, each with `entry_status` of `VALID`, `holding_status` of `HELD`, and `holder_fan_id` set to the buyer); the event's `tickets_sold_count` is increased by `quantity`; and the buyer's `completed_purchase_count` is increased by 1. The order's `version` increments. If after this the event's `tickets_sold_count` equals its `venue_capacity`, the event transitions to `SOLD_OUT` (from either `PRESALE` or `GENERAL`), and that sold-out transition in turn revokes every remaining `WAITING` queue entry for the event. No offer or order may push a tier's occupancy past its `allocation`; such an attempt is rejected with `ERR_ALLOCATION_EXCEEDED`.

A fan may abandon an unpaid order, moving it `PENDING → CANCELLED` and setting `refund_amount_cents` to 0; this releases nothing extra, because seat release on a lapsed offer is handled by queue expiry. A paid order may be refunded by its owning fan, who again supplies `expected_order_version` matching the order's current `version`. Refund is barred if any of the order's tickets is already `SCANNED`, in which case the request is rejected with `ERR_TICKET_ALREADY_SCANNED`; otherwise the order moves `PAID → REFUNDED`. The refunded amount is loyalty-tiered: the service fee is never refundable, so the refundable principal is the `subtotal_cents`. If the holder's `completed_purchase_count` is at least the loyalty threshold of 3 prior paid purchases, the full principal is refunded; otherwise the standard refund of 9000 basis points (90%) of the principal is refunded, rounded half up. The computed figure is written to `refund_amount_cents`. Refund is a depth-three compensation cascade: all of the order's tickets are voided (`entry_status → VOID`); the tier's `sold_count` is decreased by `quantity`; the event's `tickets_sold_count` is decreased by `quantity`; the buyer's `completed_purchase_count` is decreased by 1; and the order's `version` increments. If the event was `SOLD_OUT`, the freed seats re-open it `SOLD_OUT → GENERAL`.

### 3.5. Tickets and Mobile-Only Gate Entry

Every paid order issues tickets. A ticket records the issuing `order_id`, the `event_id` it admits to, the `holder_fan_id` (the current holder, which changes when a transfer completes or a resale settles), and a `seat_label` minted at issuance. A ticket carries two independent dimensions. The `entry_status` is the mobile-entry dimension — one of `VALID`, `SCANNED`, or `VOID`, defaulting to `VALID` — and the `holding_status` is the transfer/resale dimension — one of `HELD`, `TRANSFER_PENDING`, or `LISTED`, defaulting to `HELD`. These two dimensions evolve independently of each other.

A `GateScanner` admits a fan at the venue by scanning the ticket, which transitions `entry_status` from `VALID` to `SCANNED`. A scan succeeds only when the ticket's `entry_status` is `VALID`, the event's `sales_status` is one of `GENERAL`, `SOLD_OUT`, or `CLOSED`, the scan request carries a `device_channel` equal to `MOBILE`, and the ticket is not mid-transfer or listed (its `holding_status` is neither `TRANSFER_PENDING` nor `LISTED`). Mobile-only entry is strict: a scan whose `device_channel` is anything other than `MOBILE` is rejected with `ERR_NON_MOBILE_ENTRY`. A ticket also moves to `VOID` as a system cascade — when its owning order is refunded, or when it is superseded by a completed resale — and `VOID` is terminal on the entry dimension.

### 3.6. Transfers Between Fans

A holder may hand a ticket to another fan through a transfer. The sender initiates by supplying the `ticket_id`, their own `sender_fan_id`, and the `recipient_fan_id`; this is permitted only when the ticket's `holding_status` is `HELD` and its `entry_status` is `VALID`. Initiation creates a transfer in `PENDING` and moves the ticket's `holding_status` from `HELD` to `TRANSFER_PENDING`, leaving the entry dimension untouched. A transfer's `status` is one of `PENDING`, `ACCEPTED`, `DECLINED`, or `CANCELLED`. The recipient and sender must differ; a transfer whose `recipient_fan_id` equals its `sender_fan_id` is rejected with `ERR_SELF_DEALING`.

The pending transfer resolves three ways, each returning the ticket's `holding_status` to `HELD`. The recipient may accept it: acceptance requires the acting fan to be the `recipient_fan_id`, the recipient's `verification_status` to be `VERIFIED`, and the ticket to be `TRANSFER_PENDING`; it moves the transfer `PENDING → ACCEPTED`, sets the ticket's `holder_fan_id` to the recipient, and returns `holding_status` to `HELD`. The recipient may instead decline, moving the transfer `PENDING → DECLINED` and returning the ticket to `HELD` with no change of holder. Or the sender may cancel a still-pending transfer (acting fan must be the `sender_fan_id`), moving it `PENDING → CANCELLED` and returning the ticket to `HELD`. `ACCEPTED`, `DECLINED`, and `CANCELLED` are terminal.

### 3.7. The Price-Capped Resale Market

A holder who wishes to resell lists the ticket by supplying the `ticket_id`, their own `seller_fan_id`, and a `list_price_cents` asking price (greater than zero). Listing is permitted only when the ticket is `HELD` and `VALID`, and it moves the ticket's `holding_status` from `HELD` to `LISTED` while creating a listing in `OPEN`. A listing also carries a `buyer_fan_id` that is null while `OPEN` and is set on completion, and a `status` of `OPEN`, `SOLD`, or `CANCELLED`. The asking price is capped: the resale price cap in cents is the event's `face_value_cents` multiplied by the sum of 100 and the event's `resale_cap_pct`, divided by 100, rounded half up. The listing is accepted only when `list_price_cents` is at most that cap; a higher asking price is rejected with `ERR_RESALE_CAP_EXCEEDED`.

A different verified fan buys an open listing by supplying the `buyer_fan_id` and an `expected_resalelisting_version` matching the listing's current `version`. The purchase requires the listing to be `OPEN`, the buyer's `verification_status` to be `VERIFIED`, and the buyer to differ from the seller — a buyer equal to the seller is rejected with `ERR_SELF_DEALING`. On success the listing moves `OPEN → SOLD`, its `buyer_fan_id` is set to the acting fan, the underlying ticket's `holder_fan_id` becomes the buyer, the ticket's `holding_status` returns to `HELD`, and the listing's `version` increments; the ticket remains `VALID` for the new holder. A seller may withdraw an open listing instead, moving it `OPEN → CANCELLED` and returning the ticket's `holding_status` to `HELD`. `SOLD` and `CANCELLED` are terminal.

### 3.8. Verified-Fan Gates, Self-Dealing, and Bot Bars Across the Lifecycle

Two cross-cutting fairness rules thread through the workflows above. The verified-fan restriction requires the acting fan to be exactly `VERIFIED` — not `UNVERIFIED` — on six operations: joining a queue, paying an order, initiating a transfer, accepting a transfer, listing for resale, and buying a resale listing. On accept and buy it is the recipient or buyer (the acting fan) who must be verified. An unverified actor on any of these is rejected with `ERR_FAN_NOT_VERIFIED`. The bot-flag bar is stricter and is checked ahead of the verified-fan restriction: a fan whose `verification_status` is `FLAGGED` is barred with `ERR_FAN_FLAGGED` from the verified-fan check itself, queue joining, order payment, initiating and accepting transfers, and both listing and buying on resale.

The self-dealing bar applies to two operations — buying a resale listing (`buyer_fan_id` must differ from the listing's `seller_fan_id`) and initiating a transfer (`recipient_fan_id` must differ from `sender_fan_id`) — and a violation of either is `ERR_SELF_DEALING`. Ownership and self-dealing operate on the entity-backed `Fan` identity: the acting fan named by `X-User-ID` must own the order, ticket, listing, or transfer being mutated.

### 3.9. Test-Driving the Clock

Because offer expiry and the velocity window both depend on wall-clock time, a `PromoterAdmin` may pin the server's notion of "now" for deterministic testing by supplying a `to_iso8601` instant. From that point the server's current UTC reads as the supplied value until it is set again. This capability exists only to exercise offer-expiry and velocity-window behavior and has no effect on any business resource.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return a `201 Created` status code; operations that modify an existing resource, including state transitions and reads, return a `200 OK` status code. To reconstruct the full request body, side effects, and response of any endpoint, refer back to the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/fans` | Register a fan; computes risk score; lands in UNVERIFIED | Anonymous |
| POST | `/fans/{id}/verify` | Verified-fan check; resolves to VERIFIED or FLAGGED | Fan |
| GET | `/fans/{id}` | Fetch a fan | Anonymous, Fan, PromoterAdmin |
| GET | `/fans` | List fans; filterable | PromoterAdmin |
| POST | `/events` | Create an event in DRAFT | PromoterAdmin |
| GET | `/events/{id}` | Fetch an event | Anonymous, Fan, PromoterAdmin |
| GET | `/events` | List events | Anonymous, Fan, PromoterAdmin |
| POST | `/events/{id}/open-presale` | Move an event from DRAFT to PRESALE | PromoterAdmin |
| POST | `/events/{id}/open-general` | Move an event from PRESALE to GENERAL | PromoterAdmin |
| POST | `/events/{id}/close` | Close an event from GENERAL or SOLD_OUT | PromoterAdmin |
| POST | `/events/{id}/advance-queue` | Offer the next admittable entries and sweep expired offers | PromoterAdmin |
| POST | `/price-tiers` | Create a price tier under a DRAFT event | PromoterAdmin |
| GET | `/price-tiers/{id}` | Fetch a price tier | Anonymous, Fan, PromoterAdmin |
| GET | `/price-tiers` | List price tiers; filter by event | Anonymous, Fan, PromoterAdmin |
| POST | `/queue-entries` | Join the virtual queue for a tier | Fan |
| GET | `/queue-entries/{id}` | Fetch a queue entry | Fan, PromoterAdmin |
| GET | `/queue-entries` | List queue entries; filterable | Fan, PromoterAdmin |
| POST | `/orders` | Redeem an OFFERED queue entry into a PENDING order | Fan |
| POST | `/orders/{id}/pay` | Pay a pending order; issue tickets; commit seats | Fan |
| POST | `/orders/{id}/cancel` | Cancel an unpaid order | Fan |
| POST | `/orders/{id}/refund` | Refund a paid order per refund policy | Fan |
| GET | `/orders/{id}` | Fetch an order | Fan, PromoterAdmin |
| GET | `/orders` | List orders; filterable | Fan, PromoterAdmin |
| GET | `/tickets/{id}` | Fetch a ticket | Fan, PromoterAdmin, GateScanner |
| GET | `/tickets` | List tickets; filterable | Fan, PromoterAdmin, GateScanner |
| POST | `/tickets/{id}/scan` | Mobile-only gate entry scan | GateScanner |
| POST | `/transfers` | Initiate a transfer of a held ticket | Fan |
| POST | `/transfers/{id}/accept` | Recipient accepts a pending transfer | Fan |
| POST | `/transfers/{id}/decline` | Recipient declines a pending transfer | Fan |
| POST | `/transfers/{id}/cancel` | Sender cancels a pending transfer | Fan |
| GET | `/transfers/{id}` | Fetch a transfer | Fan, PromoterAdmin |
| GET | `/transfers` | List transfers; filterable | Fan, PromoterAdmin |
| POST | `/resale-listings` | List a held ticket for resale at or below the cap | Fan |
| POST | `/resale-listings/{id}/buy` | Buy an open listing | Fan |
| POST | `/resale-listings/{id}/cancel` | Seller cancels an open listing | Fan |
| GET | `/resale-listings/{id}` | Fetch a resale listing | Fan, PromoterAdmin |
| GET | `/resale-listings` | List resale listings; filterable | Anonymous, Fan, PromoterAdmin |
| POST | `/_clock/set_current_utc` | Test-driving: set the server's current UTC clock | PromoterAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_FAN_FLAGGED` | 403 |
| `ERR_INVALID_PRESALE_CODE` | 422 |
| `ERR_NON_MOBILE_ENTRY` | 422 |
| `ERR_FAN_NOT_VERIFIED` | 422 |
| `ERR_SELF_DEALING` | 422 |
| `ERR_RESALE_CAP_EXCEEDED` | 422 |
| `ERR_QTY_MISMATCH` | 422 |
| `ERR_TICKET_ALREADY_SCANNED` | 422 |
| `ERR_OFFER_EXPIRED` | 422 |
| `ERR_ALLOCATION_EXCEEDED` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 400 |

# Recreational Race Registration API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Recreational Race Registration API, a backend service that powers the full registration journey for recreational running events such as 5K fun runs and full marathons. Race organizers face two competing pressures: filling every available start slot to maximize participation and revenue, while never letting a single distance over-sell its physical capacity. The system reconciles these pressures by treating each distance as a strictly bounded pool of confirmed slots, backed by an ordered waitlist that automatically offers freed slots to the next person in line.

Beyond capacity, the platform models the commercial and operational realities of putting on a race: pricing that changes as the event approaches, group and promotional discounts, charity entries that must clear a fundraising floor before they can toe the line, bib numbers and corral letters seeded by qualifying times, transfers and deferrals between participants and events, race-week packet pickup, and timing-chip results that distinguish a runner's gun time from their personal chip time. Four cooperating roles — participants, race directors, packet staff, and timing officials — each own a slice of this workflow, and no role may perform another's exclusive work.

Because slot allocation and pricing both depend on state that several actors mutate concurrently, the API leans on explicit versioning and optimistic concurrency at the points where two writers could collide. The sections below define the global contract every endpoint obeys (§2), the business rules that govern each entity's lifecycle (§3), the endpoint catalogue (§4), and the error catalogue (§5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must be authenticated with two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly four roles, spelled precisely as follows: `Participant`, `RaceDirector`, `PacketStaff`, and `TimingOfficial`.

A `Participant` is entity-backed: when `X-User-Role` is `Participant`, the `X-User-ID` value is the `id` of the acting `Participant` record. Ownership checks on any resource that references a participant compare that resource's participant foreign key to `X-User-ID`. Concretely, a participant may only mutate a `Registration`, `FundraisingPledge`, or `TransferRequest` whose owning `participant_id` equals their `X-User-ID`; a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`. For transfer requests the ownership rule is party-specific: accepting or rejecting a transfer requires `X-User-ID` to equal the request's `to_participant_id`, while cancelling a transfer requires `X-User-ID` to equal the `from_participant_id`.

The other three roles are opaque operator identifiers not tied to any persisted entity. When `X-User-Role` is `RaceDirector`, `X-User-ID` is an opaque organizer identifier; the server may record it but does not compare it to any entity's `id`. The same holds when `X-User-Role` is `PacketStaff` (race-week staff handling packet pickup) and when `X-User-Role` is `TimingOfficial` (the official who posts and finalizes timing results and moves events to their results phase): in both cases `X-User-ID` is an opaque identifier that is never matched against a stored entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

Several list endpoints accept additional filter parameters drawn from the foreign keys and the lifecycle `status` of the resource being listed — for example registrations may be filtered by `event_id`, `distance_id`, `wave_id`, `participant_id`, `deferred_to_registration_id`, or `status`; distances by `event_id`; waves by `distance_id`; pricing tiers by `distance_id`; waitlist entries by `distance_id`, `registration_id`, `participant_id`, or `status`; pledges by `registration_id` or `status`; transfer requests by `registration_id`, `from_participant_id`, `to_participant_id`, or `status`; bib assignments by `registration_id`, `distance_id`, or `wave_id`; packet pickups by `registration_id` or `status`; and results by `registration_id`, `distance_id`, or `status`. Every entity's `status` is the exact lifecycle value defined for it in §3.

### 2.4. Common Resource Properties and Versioning

Every primary resource carries a system-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC instant with three fractional digits. Identifiers are generated by the server and are never supplied by the client.

Most resources — participants, events, distances, waves, registrations, waitlist entries, fundraising pledges, transfer requests, bib assignments, packet pickups, and result records — additionally carry an `updated_at` timestamp and an integer `version`. The `updated_at` field is refreshed on every mutation of the resource, including mutations the server performs as a cascade rather than at the client's direct request. The `version` field starts at 1 when the resource is created and increments by 1 on every mutation; it is the basis for the optimistic concurrency control described in §2.5. The one exception is the pricing tier: a `PricingTier` is immutable after creation, so it carries only `id` and `created_at` — it has neither an `updated_at` field nor a `version` field.

Computed and derived fields are mutations like any other. When the server recomputes a distance's `confirmed_count`, `charity_confirmed_count`, or `waitlist_open`, or recomputes a wave's `assigned_count`, that recomputation bumps the owning resource's `version` and refreshes its `updated_at` wherever the scaffard's transition rules call for a version increment.

### 2.5. Optimistic Concurrency Control

Two write operations contend for the same distance capacity and must guard against acting on a stale view of it. Both confirming a registration's payment and claiming an offered waitlist slot require the client to submit `expected_distance_version` in the request body, carrying the `version` of the `Distance` the client last observed.

When a participant confirms payment for a pending registration, the request must carry `expected_distance_version` equal to the target distance's current `version`. The distance's version advances whenever any registration on it confirms, cancels, defers, or is promoted from the waitlist, because each of those events changes `confirmed_count` and therefore changes whether this confirmation should succeed or fall through to the waitlist. If the submitted `expected_distance_version` does not match the distance's current `version`, the confirmation is rejected with `ERR_STALE_DISTANCE_VERSION` (HTTP 412), forcing the client to re-read the distance before retrying.

The same rule guards waitlist claims: claiming an offered slot must carry `expected_distance_version` matching the distance's current `version`. If another writer has advanced the version since the claimant last read it — possibly consuming the freed slot — the claim is rejected with `ERR_STALE_DISTANCE_VERSION` (HTTP 412), and the claimant must re-read the distance's `confirmed_count` before retrying. No other endpoint takes a version field; only payment confirmation and waitlist claim are version-guarded.

### 2.6. Capacity, Sub-Capacity, and the Waitlist Principle

Each `Distance` defines a `capacity_total`, the maximum number of registrations that may be confirmed against it, and this value must be at least 1. A distance is considered full when its `confirmed_count` reaches or exceeds `capacity_total`; the boolean `waitlist_open` is true exactly when `confirmed_count` is greater than or equal to `capacity_total`. The `confirmed_count` is the number of registrations on the distance whose status is `CONFIRMED`, `BIB_ASSIGNED`, or `FINISHED`.

Within `capacity_total`, a distance may reserve a `charity_capacity` sub-cap exclusively for charity entries; this value defaults to 0 and must be at least 0 and no greater than `capacity_total`. The `charity_confirmed_count` tracks how many confirmed registrations on the distance are charity entries. A charity registration may only confirm into a slot while `charity_confirmed_count` is below `charity_capacity`, in addition to the overall capacity test.

When a distance is full at confirmation time, the system does not raise an error; instead the registration is routed onto the waitlist (see §3.3). Each `Wave` within a distance independently caps how many registrations may be assigned to it via `wave_capacity` (at least 1) and limits how many bibs share a corral letter via `corral_capacity` (at least 1); a wave's `assigned_count` counts the bib assignments referencing it.

### 2.7. Monetary Values, Precision, and Rounding

All monetary amounts in the system are expressed as integer cents — `base_price_cents`, `amount_due_cents`, `amount_paid_cents`, `processing_fee_cents`, `refund_cents`, `deferral_credit_cents`, `charity_fundraising_minimum_cents`, `fundraising_minimum_cents`, and a pledge's `amount_cents`. There is no fractional currency. Where a calculation produces a non-integer intermediate value, the system rounds to whole cents using the half-up method for percentage-derived discounts and the pace computation, and rounds upward to the next whole cent (ceiling) for the processing fee. Fundraising totals are exact integer sums with no rounding. The specific evaluation order for each calculation is given in §3, and that order is binding — rounding a value at a different step yields a different and incorrect result.

### 2.8. Hierarchical Consistency and Cascades

Events, distances, and waves form a containment hierarchy: a `Distance` belongs to an `Event` through its `event_id`, and a `Wave` belongs to a `Distance` through its `distance_id`. A `PricingTier` likewise belongs to a distance through its `distance_id`. Registrations, waitlist entries, pledges, transfer requests, bib assignments, packet pickups, and result records are flat resources that reference these containers and each other through foreign keys rather than being nested under them.

Several operations mutate more than one resource at once. Whenever a confirmed slot on a distance is released — by cancellation, by deferral, or by a declined or withdrawn waitlist entry — the system both recomputes the distance's `confirmed_count` (bumping `Distance.version`) and, if any entries are queued, promotes the head queued waitlist entry to an offered state. Cancelling an event cascades down its entire subtree. Each such automatic mutation independently refreshes the affected resource's `updated_at` and increments its `version`; the cascading paragraphs in §3 enumerate exactly which resources move in each case, and an implementation must apply every cascade listed there, not only the primary transition.

Several operations are time-gated against the server's notion of "now": the registration window, offer expiry, results posting, and pricing-tier activation all compare against a logical current UTC clock. To make these deterministic under test, an administrative test-driving capability lets a `RaceDirector` set the server's current UTC instant by supplying the desired instant as `to_iso8601`; the clock may be advanced or rewound, and all time-gated logic thereafter evaluates against the supplied instant.

### 2.9. Nested Resource Retrieval and Referential Validation

Many paths address a resource nested under one or more parents — for example a wave under a distance, a pricing tier under a distance, or a bib assignment under a registration. For any such request, the system validates each identifier in the path from left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource, before evaluating any deeper identifier or any business rule. Body-referenced foreign keys are validated after path identifiers, also yielding `ERR_NOT_FOUND` when a referenced resource does not exist.

Existence is necessary but not sufficient: referenced resources must also be mutually consistent. When a registration is created, the requested `wave_id` must belong to the requested `distance_id`, and that distance must belong to the requested `event_id`; a pledge's target registration must be a charity entry; and a result's target registration must belong to the `distance_id` supplied with it. A violation of any of these relationship rules is rejected with `ERR_RELATION_MISMATCH` (HTTP 422).

### 2.10. Validation Ordering

When several checks apply to one request, they are evaluated in a fixed priority order so that the earliest applicable failure is the one reported. The order is: first authentication of the headers (`ERR_UNAUTHENTICATED`); then role authorization (`ERR_FORBIDDEN_ROLE`); then existence of every path- and body-referenced resource, validated left-to-right in the path before body foreign keys (`ERR_NOT_FOUND`); then resource ownership for participant-owned mutations (`ERR_NOT_RESOURCE_OWNER`); then well-formedness of the request body — required fields present and well-typed, enum values within their declared sets, `party_size` at least 1, and amounts at least 1 where required (`ERR_INVALID_REQUEST`); then cross-resource relationship consistency on registration, pledge, and result creation (`ERR_RELATION_MISMATCH`); then whether the target resource is in a valid state for the requested transition (`ERR_INVALID_STATE`). Only after all of these pass does the system evaluate the domain-specific business rules described throughout §3 — temporal windows, pricing-tier availability, fundraising minimums, wave and distance capacity, the concurrency version check, packet eligibility, pricing-tier uniqueness, timing well-ordering, and deferral target validity — each of which carries its own error described where the rule is defined.

## 3. Business Logic & Workflows

### 3.1. Setting Up an Event: Distances, Waves, and Pricing Tiers

Before anyone can register, a person must exist as a `Participant` account. An account is created with a unique `email`, a `full_name`, a `birthdate` given as an ISO date in `YYYY-MM-DD` form (used to derive the runner's age on race day), and a `gender` of `M`, `F`, or `X`. A participant's `email` must be unique across all participants. Account creation may be performed either by the person registering themselves or by a `RaceDirector` on their behalf.

A `RaceDirector` builds the catalogue from the top down. They first create an `Event` with a `name`, a `race_date_utc` marking the race-day start instant, and the registration window bounds `registration_opens_utc` and `registration_closes_utc`. A new event begins life in `DRAFT`. The director then adds one or more distances to the event, each created with a `label` drawn from `FIVE_K`, `TEN_K`, `HALF_MARATHON`, or `MARATHON`, a `distance_km` course length such as 5.0 or 42.195, a `capacity_total`, and optionally a `charity_capacity` and a `charity_fundraising_minimum_cents` floor. Within a distance, the director defines waves — each with a `name` such as "Wave 1 - 07:00", a `start_offset_seconds` measured from the gun start, a `wave_capacity`, and a `corral_capacity` — and date-based pricing tiers.

Each `PricingTier` carries a `tier_name` of `EARLY_BIRD`, `REGULAR`, or `LATE`, an `effective_from_utc` instant from which it becomes active, and a `base_price_cents` entry fee charged to a standard registration created while that tier is active. The active tier for a given reference clock is the tier on the distance whose `effective_from_utc` is the greatest instant that is still less than or equal to the reference clock; an `effective_from_utc` exactly equal to the reference clock counts as active. Because tiers tile the timeline as half-open windows, two tiers on the same distance may never share the same `effective_from_utc`: an attempt to add a tier whose `effective_from_utc` equals that of an existing tier on the distance is rejected with `ERR_DUPLICATE_PRICING_TIER`.

Before an event can open for registration, the director transitions it from `DRAFT` to `OPEN`. This transition is permitted only when the event has at least one distance that itself has at least one wave and at least one pricing tier, and only when the current clock is at or after `registration_opens_utc`; opening before that instant is rejected with `ERR_REGISTRATION_CLOSED`. Opening the event allows registrations to be created against its distances and increments the event's `version`. The director can later move an `OPEN` event to `CLOSED`, which rejects any new registration creation with `ERR_REGISTRATION_CLOSED` but still allows existing confirmed registrations to be assigned bibs and to pick up packets; this too increments the event's `version`.

### 3.2. Joining a Race: Creating and Pricing a Registration

A `Participant` joins a race by creating a `Registration`, supplying the `event_id`, the chosen `distance_id`, the requested `wave_id`, and the `participant_id` of the registrant. The optional `entry_type` is `STANDARD` or `CHARITY`, defaulting to `STANDARD`. A new registration begins in `PENDING_PAYMENT`. Creation is only permitted while the owning event is `OPEN` and the current clock falls within the registration window — at or after `registration_opens_utc` and strictly before `registration_closes_utc`, the upper bound being exclusive; outside that window the creation is rejected with `ERR_REGISTRATION_CLOSED`. The relationship checks of §2.9 apply: the wave must belong to the distance and the distance to the event.

At creation the system computes a provisional charge and stores it in `amount_due_cents`, using the registration's `created_at` as the reference clock. The pricing follows a pinned sequence of steps, and the order matters because the discount depends on the base fee while the processing fee depends on the discounted base. First, the base fee is the active pricing tier's `base_price_cents` for the distance at the reference clock; if no tier is active because the reference clock precedes the earliest `effective_from_utc`, the request is rejected with `ERR_NO_ACTIVE_PRICING_TIER`. For a charity entry the base fee is instead 0 — the entry fee is waived. Second, a group discount percentage is derived from the registrant's `party_size` (which defaults to 1 and must be at least 1): a party of at least 4 earns 0.10, a party of at least 2 but fewer than 4 earns 0.05, and a solo registrant earns 0.00. Third, an optional `promo_code` maps to a promotional discount percentage through a fixed table in which `SPRING10` is worth 0.10 and `WELCOME05` is worth 0.05; any other or absent code is worth 0.00. Fourth, the group and promo percentages are added together and then capped at the maximum total discount of 0.20. Fifth, the discount in cents is the base multiplied by that capped percentage, rounded half-up to a whole cent. Sixth, the discounted base is the base minus that discount. Seventh, the processing fee in cents is the discounted base multiplied by the processing fee rate of 0.029, rounded up to the next whole cent. Finally, the amount is the discounted base plus the processing fee.

The registrant may also supply a `qualifying_time_seconds` self-reported seed time used later for corral seeding; it may be omitted (null) for an unseeded runner. For a charity entry, the system at creation copies the distance's `charity_fundraising_minimum_cents` into the registration's `fundraising_minimum_cents`; for a standard entry that minimum is 0. The provisional `amount_due_cents` is only an estimate: no charge is captured at creation, `amount_paid_cents` and `processing_fee_cents` remain 0, and `refund_cents`, `deferral_credit_cents`, and `deferred_to_registration_id` are likewise unset until the relevant later event.

### 3.3. Confirming Payment, Capacity, and the Waitlist

A participant confirms payment on their own pending registration to lock in a slot. Confirmation is only valid from `PENDING_PAYMENT`; attempting it from any other status is rejected with `ERR_INVALID_STATE`. The owning event must be `OPEN`, and the request must carry `expected_distance_version` matching the distance's current `version` as described in §2.5, failing which it is rejected with `ERR_STALE_DISTANCE_VERSION`.

The outcome forks on capacity. If the distance has room — its `confirmed_count` is below `capacity_total`, and for a charity entry its `charity_confirmed_count` is below `charity_capacity` — the registration advances from `PENDING_PAYMENT` to `CONFIRMED`. At that moment the system captures the final charge into `amount_paid_cents`, recording the `processing_fee_cents` component, computed with the very same pinned pricing sequence as the provisional estimate but now using the confirm-time clock as the reference. If the active tier changed between creation and confirmation, this final figure legitimately diverges from `amount_due_cents`. Confirmation increments the distance's `confirmed_count` (and `charity_confirmed_count` for a charity entry) and bumps `Distance.version`. If instead the distance is full — `confirmed_count` is greater than or equal to `capacity_total`, or for a charity entry the charity sub-cap is full — the registration is routed to `WAITLISTED` rather than erroring, no charge is captured, `amount_paid_cents` stays 0, and the system creates a `WaitlistEntry` for this registration on the distance in the `QUEUED` state.

Each `WaitlistEntry` records the `distance_id` it queues against, the `registration_id` parked on it, and the `participant_id` of the queued registrant, and it begins in `QUEUED`. Its `queue_position` is its 1-based position by ascending `created_at` among the queued entries on that distance. When a confirmed slot is freed on a distance and at least one entry is queued, the head queued entry — the one with the lowest `created_at` — is promoted to `OFFERED`, provided the distance now has room (`confirmed_count` below `capacity_total`). Promotion stamps `offer_expires_utc` to the current clock plus the offer time-to-live of 24 hours and bumps that entry's `version`.

A participant holding an `OFFERED` entry may claim it, which is only valid while the entry is `OFFERED` and the current clock is strictly before `offer_expires_utc`; a claim at or after that instant is rejected with `ERR_OFFER_EXPIRED`. The claim also requires the distance to still have room (`confirmed_count` below `capacity_total`) — an explicit claim against a full distance is rejected with `ERR_DISTANCE_FULL` — and requires `expected_distance_version` to match per §2.5. A successful claim moves the entry from `OFFERED` to `CLAIMED`, transitions the linked registration from `WAITLISTED` to `CONFIRMED` capturing the charge through the same final pricing computation, increments the distance's `confirmed_count`, and bumps `Distance.version`. Alternatively the offered participant may decline, moving the entry from `OFFERED` to `DECLINED`, which cancels the linked registration and promotes the next queued entry to `OFFERED`. A still-queued entry may instead be withdrawn, moving it from `QUEUED` to `WITHDRAWN` and cancelling the linked registration. Finally, an offered entry whose window has elapsed is swept by the race director's expiry check: when the current clock is at or after `offer_expires_utc`, the entry moves from `OFFERED` to `EXPIRED`, and the next queued entry on the distance (lowest `created_at`) is promoted to `OFFERED` with its own `offer_expires_utc` stamped.

### 3.4. Cancelling, Transferring, and Deferring a Registration

A participant may cancel their own registration from any of `PENDING_PAYMENT`, `CONFIRMED`, `BIB_ASSIGNED`, or `WAITLISTED`; cancelling from any other status is rejected with `ERR_INVALID_STATE`. Cancellation moves the registration to terminal `CANCELLED` and computes `refund_cents`. For a participant-initiated cancellation the refund follows a pinned order: if the registration was in `PENDING_PAYMENT` or `WAITLISTED` nothing was ever captured, so the refund is 0; otherwise the net base is `amount_paid_cents` minus `processing_fee_cents` (the processing fee is never refunded), the cancellation fee is that net multiplied by the cancellation fee rate of 0.15 rounded half-up to a whole cent, and the refund is the net minus that independently-rounded fee. The fee component is rounded first and then subtracted — the system does not subtract a fractional fee and round the whole refund afterward.

If the cancelled registration had been `CONFIRMED` or `BIB_ASSIGNED`, the distance's `confirmed_count` is decremented (and `charity_confirmed_count` for a charity entry) and `Distance.version` is bumped; if it had been `BIB_ASSIGNED`, the associated `BibAssignment` is deleted, the wave's `assigned_count` is decremented, and `Wave.version` is bumped. Because cancelling a confirmed registration frees a slot, the head queued waitlist entry on that distance is promoted to `OFFERED` and its `version` bumped, exactly as in §3.3. Any still-`PROPOSED` transfer request on the cancelled registration is itself moved to `CANCELLED`.

Transfers let one participant hand a confirmed slot to another. The current registrant proposes a `TransferRequest` by supplying the `registration_id` of a confirmed registration and the `to_participant_id` of the proposed new registrant; the `from_participant_id` is taken from the registration's current owner, and the request begins `PROPOSED`. The proposed recipient accepts the transfer, which requires the acting participant to be the `to_participant_id`, the linked registration to still be `CONFIRMED` (not yet bib-assigned), and the owning event to be `OPEN`. Acceptance moves the transfer to `ACCEPTED`, moves the original registration to terminal `TRANSFERRED`, and creates a new `Registration` for the recipient that inherits the same distance and wave, starts already `CONFIRMED` with `amount_paid_cents` of 0 because the paid slot simply carries over, and takes `entry_type` `STANDARD`. The distance's `confirmed_count` is unchanged because the slot moves rather than being freed, but `Distance.version` is still bumped. The recipient may instead reject the transfer, moving it to `REJECTED` and leaving the registration `CONFIRMED`; or the original proposer may cancel their own proposal, moving it to `CANCELLED` and again leaving the registration `CONFIRMED`. Rejection requires the acting participant to be the `to_participant_id`, while cancellation requires the acting participant to be the `from_participant_id`.

Deferral lets a confirmed participant roll their entry into a different event. Deferring is valid only from `CONFIRMED` and requires a `target_event_id` in the body whose event is in `DRAFT` or `OPEN`, differs from the current event, and offers a distance whose `label` matches the source distance's label; a target failing any of these conditions is rejected with `ERR_TARGET_EVENT_INVALID`. Deferral computes `deferral_credit_cents` as the net base — `amount_paid_cents` minus the non-transferable `processing_fee_cents` — reduced by the deferral fee of 1500 cents, with the result floored at 0 so the credit is never negative. The original registration moves to terminal `DEFERRED`, a new `PENDING_PAYMENT` registration is created on the target event's matching distance with `deferred_to_registration_id` on the original pointing to it, the original distance's `confirmed_count` is decremented and `Distance.version` bumped, and the freed slot promotes the head queued waitlist entry to `OFFERED`.

### 3.5. Charity Entries and Fundraising

A charity registration must raise money before it can be issued a bib. Each `FundraisingPledge` records the `registration_id` of the charity registration it funds, a `donor_name`, and an `amount_cents` that must be at least 1, and begins in `PLEDGED`. A pledge may only target a charity registration; pledging against a standard entry is a relationship violation rejected with `ERR_RELATION_MISMATCH`. The participant may settle a pledge, moving it from `PLEDGED` to `SETTLED`, which is permitted only while the linked registration is a charity entry and is not `CANCELLED`. Any pledge in `PLEDGED` or `SETTLED` may be voided, moving it to terminal `VOIDED`.

Fundraising progress is measured two ways from the same pledge rows. The provisional, optimistic total sums `amount_cents` over the registration's pledges that are either `PLEDGED` or `SETTLED`, and is used for informational display. The final, settled total sums `amount_cents` over only the `SETTLED` pledges. Voided pledges are excluded from both totals. The settled total is the figure that gates bib assignment for charity entries, as described in §3.6.

### 3.6. Bib and Corral Assignment

Once a registration is `CONFIRMED`, a `RaceDirector` assigns it a bib, advancing it from `CONFIRMED` to `BIB_ASSIGNED`; attempting assignment from any other status is rejected with `ERR_INVALID_STATE`. For a charity entry the assignment is gated on fundraising: the settled fundraising total must be at least the registration's `fundraising_minimum_cents`, and a shortfall is rejected with `ERR_FUNDRAISING_MINIMUM_NOT_MET`. The requested wave must also have room — its `assigned_count` must be strictly below its `wave_capacity` — and a full wave is rejected with `ERR_WAVE_FULL`.

A successful assignment creates a `BibAssignment` recording the `registration_id`, the denormalized `distance_id`, and the `wave_id`, together with a computed `bib_number` and `corral` letter. The corral is seeded within the assigned wave: the system ranks every registration that already holds a bib assignment in that wave together with the one now being assigned, ordering them first by ascending `qualifying_time_seconds` — with an unseeded (null) qualifying time sorting last — and breaking ties by ascending `created_at` (never by `id`). With ranks counted from 0, the corral index is the rank divided by the wave's `corral_capacity` discarding any remainder, and the corral letter is the letter at that offset from `A`: index 0 is `A`, index 1 is `B`, index 2 is `C`, and so on. The `bib_number` is the next sequential integer within the distance, starting at 100 and handed out to bib assignments in ascending `created_at` order. Assignment increments the wave's `assigned_count` and bumps `Wave.version`.

### 3.7. Race Week: Packet Pickup

During race week a `PacketStaff` member issues a packet to a registrant. A `PacketPickup` records the `registration_id`, the `picked_up_by_name` of the person collecting it, and an `id_verified` flag indicating whether photo identification was checked (defaulting to false); it begins `ISSUED`. Pickup is only eligible when the registration is `CONFIRMED` or `BIB_ASSIGNED`; any other status is rejected with `ERR_PACKET_NOT_ELIGIBLE`. A registration may hold at most one `ISSUED` packet pickup at a time, so attempting to issue a second while one is still issued is rejected with `ERR_PACKET_ALREADY_ISSUED`. Packet staff may void an issued pickup, moving it from `ISSUED` to terminal `VOIDED`, after which the registration becomes eligible to pick up a packet again.

### 3.8. Timing Results and Finishing

After the race, a `TimingOfficial` moves the event forward and records results. An event may be moved from `CLOSED` to `RESULTS_POSTED` only while it is `CLOSED` and the current clock is at or after `race_date_utc`; posting results before race day is rejected with `ERR_REGISTRATION_CLOSED`. Posting results enables provisional result records to be finalized.

A timing official posts a `ResultRecord` for a bib-assigned registration by supplying the `registration_id`, the `distance_id`, and three clock readings in seconds: the wave's `gun_start_clock_seconds`, the `mat_cross_clock_seconds` when the chip crossed the start mat, and the `finish_clock_seconds` at the finish line. The record begins `PROVISIONAL`. The clocks must be well-ordered — the mat crossing at or after the gun start, and the finish strictly after the mat crossing — and any other ordering is rejected with `ERR_INVALID_TIMING`. From these, the system derives two times: the gun time, used for official placement, is the finish clock minus the gun-start clock; the chip time, the personal net time, is the finish clock minus the mat-crossing clock. These populate `gun_time_seconds` and `chip_time_seconds`. The pace, stored in `pace_seconds_per_km`, is the chip time divided by the distance's `distance_km`, rounded half-up to a whole number of seconds.

A provisional result is finalized to `OFFICIAL` by a timing official, which is permitted only while the owning event is `RESULTS_POSTED` and the linked registration is `BIB_ASSIGNED`; finalization freezes the gun time, chip time, and pace as official. A result in either `PROVISIONAL` or `OFFICIAL` may instead be disqualified to terminal `DQ` on protest, which excludes it from rankings and prevents the linked registration from being marked finished. Finally, a timing official marks a bib-assigned registration as finished, advancing it from `BIB_ASSIGNED` to terminal `FINISHED`; this is permitted only when the registration is `BIB_ASSIGNED`, the owning event is `CLOSED` or `RESULTS_POSTED`, and an `OFFICIAL` result record exists for the registration.

### 3.9. Cancelling an Event

A `RaceDirector` may cancel an event from `DRAFT`, `OPEN`, or `CLOSED`; cancellation is forbidden once the event has reached `RESULTS_POSTED`. Cancelling moves the event to terminal `CANCELLED`, increments `Event.version`, and cascades across the whole event. Every non-terminal registration on every distance of the event is moved to `CANCELLED`, which in turn releases that distance's capacity and recomputes `confirmed_count`; every `QUEUED` or `OFFERED` waitlist entry on every distance is moved to `WITHDRAWN`. Because this cancellation is organizer-initiated rather than participant-initiated, the refund rule is overridden: each previously `CONFIRMED` or `BIB_ASSIGNED` registration receives a full refund of `amount_paid_cents` including the processing fee, with no cancellation fee.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return a `201 Created` status code. Operations that modify an existing resource — including the state-transition operations that drive the various workflows — return a `200 OK` status code, except for bib assignment, which mints a new `BibAssignment` resource and therefore returns `201 Created`. The test-driving clock endpoint returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/participants` | Register a participant account | RaceDirector, Participant |
| GET | `/participants/{participant_id}` | Read a participant | RaceDirector, Participant, PacketStaff, TimingOfficial |
| POST | `/events` | Create a race event (DRAFT) | RaceDirector |
| GET | `/events/{event_id}` | Read an event | RaceDirector, Participant, PacketStaff, TimingOfficial |
| POST | `/events/{event_id}/open` | Open registration | RaceDirector |
| POST | `/events/{event_id}/close` | Close registration | RaceDirector |
| POST | `/events/{event_id}/post-results` | Move event to RESULTS_POSTED | TimingOfficial |
| POST | `/events/{event_id}/cancel` | Cancel an event and cascade-cancel registrations and waitlist | RaceDirector |
| POST | `/events/{event_id}/distances` | Create a distance under an event | RaceDirector |
| GET | `/events/{event_id}/distances` | List distances for an event | RaceDirector, Participant, PacketStaff, TimingOfficial |
| GET | `/distances/{distance_id}` | Read a distance (includes computed counts and version) | RaceDirector, Participant, PacketStaff, TimingOfficial |
| GET | `/distances` | List/filter distances | RaceDirector, Participant, PacketStaff, TimingOfficial |
| POST | `/distances/{distance_id}/waves` | Create a wave under a distance | RaceDirector |
| GET | `/distances/{distance_id}/waves` | List waves for a distance | RaceDirector, Participant, PacketStaff, TimingOfficial |
| GET | `/waves/{wave_id}` | Read a wave | RaceDirector, Participant, PacketStaff, TimingOfficial |
| GET | `/waves` | List/filter waves | RaceDirector, Participant, PacketStaff, TimingOfficial |
| POST | `/distances/{distance_id}/pricing-tiers` | Add a date-based pricing tier to a distance | RaceDirector |
| GET | `/pricing-tiers/{pricing_tier_id}` | Read a pricing tier | RaceDirector, Participant, PacketStaff, TimingOfficial |
| GET | `/pricing-tiers` | List/filter pricing tiers | RaceDirector, Participant, PacketStaff, TimingOfficial |
| POST | `/registrations` | Create a registration (PENDING_PAYMENT); computes provisional amount due | Participant |
| GET | `/registrations/{registration_id}` | Read a registration | RaceDirector, Participant, PacketStaff, TimingOfficial |
| GET | `/registrations` | List/filter registrations | RaceDirector, Participant, PacketStaff, TimingOfficial |
| POST | `/registrations/{registration_id}/confirm-payment` | Confirm payment; CONFIRMED if capacity available else WAITLISTED | Participant |
| POST | `/registrations/{registration_id}/cancel` | Cancel a registration; refund computed; cascade waitlist promotion | Participant |
| POST | `/registrations/{registration_id}/assign-bib` | Assign bib and corral to a CONFIRMED registration | RaceDirector |
| POST | `/registrations/{registration_id}/defer` | Defer a CONFIRMED registration to another event | Participant |
| POST | `/registrations/{registration_id}/finish` | Mark a bib-assigned registration FINISHED after official result | TimingOfficial |
| GET | `/registrations/{registration_id}/bib-assignments` | List bib assignments for a registration | RaceDirector, Participant, PacketStaff, TimingOfficial |
| GET | `/registrations/{registration_id}/fundraising-pledges` | List pledges for a registration | RaceDirector, Participant, PacketStaff, TimingOfficial |
| GET | `/registrations/{registration_id}/packet-pickups` | List packet pickups for a registration | RaceDirector, Participant, PacketStaff, TimingOfficial |
| GET | `/registrations/{registration_id}/results` | List results for a registration | RaceDirector, Participant, PacketStaff, TimingOfficial |
| GET | `/waitlist-entries/{waitlist_entry_id}` | Read a waitlist entry | RaceDirector, Participant |
| GET | `/distances/{distance_id}/waitlist-entries` | List waitlist entries for a distance | RaceDirector, Participant |
| GET | `/waitlist-entries` | List/filter waitlist entries | RaceDirector, Participant |
| POST | `/waitlist-entries/{waitlist_entry_id}/claim` | Claim an OFFERED waitlist slot (confirms the linked registration) | Participant |
| POST | `/waitlist-entries/{waitlist_entry_id}/decline` | Decline an OFFERED waitlist slot | Participant |
| POST | `/waitlist-entries/{waitlist_entry_id}/withdraw` | Withdraw a QUEUED waitlist entry | Participant |
| POST | `/waitlist-entries/{waitlist_entry_id}/expire-check` | System sweep: expire an OFFERED slot whose offer window elapsed | RaceDirector |
| POST | `/pledges` | Record a fundraising pledge for a CHARITY registration | Participant |
| GET | `/pledges/{pledge_id}` | Read a pledge | RaceDirector, Participant |
| GET | `/pledges` | List/filter pledges | RaceDirector, Participant |
| POST | `/pledges/{pledge_id}/settle` | Settle a pledge (counts toward final fundraising total) | Participant |
| POST | `/pledges/{pledge_id}/void` | Void a pledge | Participant |
| POST | `/transfer-requests` | Propose transferring a CONFIRMED registration to another participant | Participant |
| GET | `/transfer-requests/{transfer_request_id}` | Read a transfer request | RaceDirector, Participant |
| GET | `/transfer-requests` | List/filter transfer requests | RaceDirector, Participant |
| GET | `/registrations/{registration_id}/transfer-requests` | List transfer requests for a registration | RaceDirector, Participant |
| POST | `/transfer-requests/{transfer_request_id}/accept` | Recipient accepts; registration transfers | Participant |
| POST | `/transfer-requests/{transfer_request_id}/reject` | Recipient rejects the transfer | Participant |
| POST | `/transfer-requests/{transfer_request_id}/cancel` | Proposer cancels the transfer | Participant |
| GET | `/bib-assignments/{bib_assignment_id}` | Read a bib assignment | RaceDirector, Participant, PacketStaff, TimingOfficial |
| GET | `/bib-assignments` | List/filter bib assignments | RaceDirector, Participant, PacketStaff, TimingOfficial |
| GET | `/waves/{wave_id}/bib-assignments` | List bib assignments in a wave | RaceDirector, Participant, PacketStaff, TimingOfficial |
| GET | `/distances/{distance_id}/bib-assignments` | List bib assignments in a distance | RaceDirector, Participant, PacketStaff, TimingOfficial |
| POST | `/packet-pickups` | Issue a packet pickup for a CONFIRMED/BIB_ASSIGNED registration | PacketStaff |
| GET | `/packet-pickups/{pickup_id}` | Read a packet pickup | RaceDirector, Participant, PacketStaff |
| GET | `/packet-pickups` | List/filter packet pickups | RaceDirector, Participant, PacketStaff |
| POST | `/packet-pickups/{pickup_id}/void` | Void a packet pickup | PacketStaff |
| POST | `/results` | Post a timing-chip result for a bib-assigned registration | TimingOfficial |
| GET | `/results/{result_id}` | Read a result record | RaceDirector, Participant, PacketStaff, TimingOfficial |
| GET | `/results` | List/filter results | RaceDirector, Participant, PacketStaff, TimingOfficial |
| GET | `/distances/{distance_id}/results` | List results for a distance | RaceDirector, Participant, PacketStaff, TimingOfficial |
| POST | `/results/{result_id}/finalize` | Mark a result OFFICIAL | TimingOfficial |
| POST | `/results/{result_id}/disqualify` | Disqualify a result | TimingOfficial |
| POST | `/_clock/set_current_utc` | Test-driving endpoint: set the server's current UTC clock | RaceDirector |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_RELATION_MISMATCH` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_REGISTRATION_CLOSED` | 409 |
| `ERR_OFFER_EXPIRED` | 409 |
| `ERR_NO_ACTIVE_PRICING_TIER` | 409 |
| `ERR_FUNDRAISING_MINIMUM_NOT_MET` | 409 |
| `ERR_WAVE_FULL` | 409 |
| `ERR_DISTANCE_FULL` | 409 |
| `ERR_STALE_DISTANCE_VERSION` | 412 |
| `ERR_PACKET_ALREADY_ISSUED` | 409 |
| `ERR_PACKET_NOT_ELIGIBLE` | 409 |
| `ERR_INVALID_TIMING` | 422 |
| `ERR_TARGET_EVENT_INVALID` | 409 |
| `ERR_DUPLICATE_PRICING_TIER` | 409 |

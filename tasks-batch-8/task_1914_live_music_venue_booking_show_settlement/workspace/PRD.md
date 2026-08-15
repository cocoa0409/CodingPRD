# Live Music Venue Booking API — Product Requirements Document

## 1. Introduction

An independent live-music venue runs on two calendars at once: the booking calendar, where agents hold, challenge, and confirm dates on behalf of their artists, and the settlement ledger, where every guarantee, door split, expense receipt, and ancillary split is reconciled after the house lights come up. This document specifies the API for the venue's booking-and-settlement platform, which manages the full arc of a show — from the first competing date hold, through deal negotiation and ticketing, the production advance, night-of settlement, and the wire transfers that pay everyone out.

The platform serves five operator roles with deliberately segregated duties: the people who book and negotiate are never the people who settle, and the person who submits a settlement is never the person who approves it. It models competing date holds through a formal priority-and-challenge protocol, supports the three deal structures common in independent rooms (flat guarantee, door split, and guarantee-versus-split), and computes night-of settlement as an explicit, auditable waterfall in integer cents. Cancellation and postponement — including force-majeure events — follow a published penalty policy so that artist, venue, and support acts all know their exposure before anyone signs.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming that operator's role. A request with either header missing or malformed, or carrying a role the platform does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). An authenticated operator whose role is not on the target endpoint's authorized list is rejected with `ERR_FORBIDDEN` (HTTP 403).

The platform recognizes exactly five roles, spelled exactly as follows: `VenueManager`, `BookingAgent`, `Promoter`, `ProductionManager`, and `Accountant`. The `VenueManager` is the venue operator and owns the artist roster, the agent roster, the venue side of offer negotiation, expense-receipt adjudication, postponements, and the house clock. The `BookingAgent` represents an artist: placing, challenging, confirming, and releasing date holds, negotiating offers from the artist side, cancelling on the artist's behalf, and disputing settlements. The `Promoter` runs the show commercially: ticket tiers, on-sale, ticket sales and refunds, support acts, expense and ancillary submissions, and settlement drafting and submission. The `ProductionManager` owns the advance checklist and the advance-completion step. The `Accountant` approves settlements and operates every wire transfer.

When `X-User-Role` is `BookingAgent`, `X-User-ID` is the `id` of the acting `BookingAgent` entity; ownership checks on any resource that references a `BookingAgent` — most importantly a date hold's `booked_by_agent_id` and a challenge's `challenger_agent_id` — compare the resource's foreign-key field to `X-User-ID`. The other four roles are opaque: when `X-User-Role` is `VenueManager`, `Promoter`, `ProductionManager`, or `Accountant`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — as `submitted_by_user_id` on a settlement when a `Promoter` submits, or as `approved_by_user_id` when an `Accountant` approves — but it does not compare it to any entity's `id`. This opacity is what makes segregation of duties meaningful: settlement approval compares the approver's opaque `X-User-ID` against the recorded `submitted_by_user_id`, and equality is a rejection, as detailed in §3.7.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, accepts a minimum of 1, and is capped at a maximum of 100; the `offset` parameter defaults to 0. Every list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more` inside `meta`. All list endpoints sort by `created_at` ascending, oldest record first.

### 2.4. Resource Identity and Bookkeeping Metadata

Every persisted resource carries an `id` minted by the server as a UUID, with no type prefix of any kind. Every resource also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits. Most resources additionally carry `updated_at`, refreshed on every mutation, and `version`, an integer that increments by one on every mutation of that resource.

Three ledger-style records are the exception, and the exception is explicit: a `TicketSale`, an `AncillaryRevenue` row, and a `CancellationEvent` each carry only `id` and `created_at`. Both `updated_at` and `version` are absent from these three entities — they are append-only records of the night, never mutated in place, and no concurrency protocol ever reads their version.

### 2.5. House Money Rules: Integer Cents and Half-Up Rounding

All monetary values everywhere in the platform are integer cents — guarantees, ticket faces, expenses, ancillary receipts, wire amounts, and every computed settlement figure. Wherever a calculation prescribes a rounding step, that step rounds half up to the nearest whole cent; products and sums that are not explicit rounding steps are never rounded, so intermediate values flow through the waterfall at full precision. Percentages and splits are carried as plain fractions in inputs such as `deposit_pct`, `artist_split_pct`, `bar_split_pct`, and `merch_split_pct`.

### 2.6. Version Checks on the Show Spine (Optimistic Concurrency)

Four write operations sit on the show's critical path and therefore take a mandatory optimistic-concurrency field: confirming a date hold, accepting an offer, placing a show on sale, and submitting a settlement. Each of these requests must carry `expected_show_version`, set to the show's `version` as the caller last observed it. If the show's current `version` has advanced beyond that observed value — because a deposit wire completed, a competing hold confirmed, another offer was accepted, or any other mutation landed in between — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), protecting the caller from writing against a show it has not seen.

Each of these four operations increments the show's `version` by exactly one on success. No endpoint outside these four accepts a version field at all; any other write is taken as-is against current state. The stale-version check concerns what the caller has observed, not when requests arrive: it fires whenever the presented version no longer matches, regardless of how the version advanced.

### 2.7. The House Clock

The platform runs on a logical clock rather than wall-clock time. At server startup, before any clock-setting call, the logical clock reads exactly 2026-08-01T00:00:00Z and never falls back to wall-clock time. A `VenueManager`-only capability advances the logical clock to a supplied `to_iso8601` instant. Advancing the clock triggers the time-based transitions of the domain — date holds whose expiry instants have passed lapse to `EXPIRED`, and an `ADVANCED` show whose doors-open instant has arrived moves to `SHOW_NIGHT` — with these checks evaluated lazily on the next read or write that touches the affected resource.

### 2.8. The Request Gauntlet: Validation Order and Error Precedence

Every request walks a fixed validation pipeline, and the first failure stops evaluation and determines the response — an earlier failure is never masked by a later check. The order is:

1. Authentication of the `X-User-ID` and `X-User-Role` headers; failures yield `ERR_UNAUTHENTICATED` (HTTP 401).
2. Authorization of the caller's role against the endpoint's role list; failures yield `ERR_FORBIDDEN` (HTTP 403).
3. Existence of every path-template resource — show, hold, offer, deal, tier, sale, advance item, support act, receipt, ancillary row, settlement, wire — evaluated left to right along the path; the first miss yields `ERR_NOT_FOUND` (HTTP 404).
4. Existence of body-referenced foreign keys (`artist_id`, `tier_id`, `recipient_artist_id`, `support_act_id`, `settlement_id`) on creation endpoints; a dangling reference yields `ERR_NOT_FOUND` (HTTP 404).
5. From-state validity for the requested transition, per the state machines of §3; failures yield `ERR_INVALID_STATE` (HTTP 409). When the target entity is already in a terminal state and no transition is defined at all, the rejection is `ERR_ALREADY_TERMINAL` (HTTP 409).
6. Optimistic-concurrency staleness on the four versioned endpoints of §2.6; a mismatch yields `ERR_STALE_VERSION` (HTTP 412).
7. Business rules, in their own fixed sequence: the low-ticket-sales cancellation gate, then the deposit-clearance gate on going on sale, then hold-expiry timing on confirms, then challenge priority, then show-schedule validity, then tier capacity, then ticket availability, then the support budget, then deal terms, then the guarantee floor, then wire-amount matching, then settlement readiness, then segregation of duties, and finally the self-negotiation bar.

The relative order matters wherever two rules guard the same endpoint. An offer whose terms fail the deal-shape check reports `ERR_INVALID_DEAL_TERMS` even if its guarantee is also below the artist's floor, because deal terms (rule 15) precede the guarantee floor (rule 16). A hold confirmation carrying a stale `expected_show_version` reports `ERR_STALE_VERSION` rather than `ERR_HOLD_EXPIRED`, because staleness (rule 6) precedes expiry timing (rule 9). A settlement submission with both a stale version and outstanding `PENDING` receipts reports `ERR_STALE_VERSION`, since readiness (rule 18) is evaluated only after the version check passes. Independently of this pipeline, a request whose required fields are missing, malformed, or ill-typed is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.9. Walking the Path: Nested Resource Existence

Most operational resources hang beneath a show, and their URLs reflect that nesting. Path existence is validated strictly left to right: the `id` of the show first, then the child identifier — `hold_id`, `offer_id`, `tier_id`, `sale_id`, `receipt_id`, `support_act_id`, `wire_id`, or the advance `item_name` — within that show. The first segment that fails to resolve produces the `ERR_NOT_FOUND` response; a request that names a perfectly good hold under a nonexistent show reports the missing show, not the hold. The advance `item_name` segment resolves against the six checklist item names of §3.5, and any other value is an `ERR_NOT_FOUND`.

## 3. Business Logic & Workflows

### 3.1. Building the Roster: Artists and Booking Agents

A `VenueManager` onboards each artist with the artist or band `legal_name`, the `agency` that represents them, a `guarantee_floor_cents` expressing the minimum guarantee the artist will accept in cents, and a `deposit_pct` — the fraction of the guarantee required up front as a deposit, carried as a value between 0.0 and 0.5 inclusive. The artist's `status` is either `ACTIVE` or `SUSPENDED`. Once shows begin settling, the artist's `total_settled_shows` tracks how many of their shows have reached `SETTLED`; it is a computed counter, never set by hand, and it ticks upward by one each time one of the artist's shows completes settlement.

Booking agents enter the roster the same way, created by a `VenueManager` with a `display_name` and an `agency_name`, and likewise carry a `status` of `ACTIVE` or `SUSPENDED`. Because the agent's identity is entity-backed (§2.1), every hold the agent places and every challenge the agent mounts is attributable back to this roster record. The guarantee floor recorded here is not decorative: §3.3's negotiation rules refuse offers that dip below it.

### 3.2. Holding the Date: Show Creation and the Hold Contest

A show begins when a `BookingAgent` or `VenueManager` creates it, naming the headliner through `artist_id` — which must reference an existing artist, or the create fails with `ERR_NOT_FOUND` — along with the `room` (either `MAIN_ROOM` or `LOUNGE`), the `show_date` as an ISO-8601 date, the `doors_at_utc` and `curfew_at_utc` timestamps, the `total_capacity` across all ticket tiers, and the planned public `on_sale_at_utc`. The house enforces a booking lead time and a sane schedule: the `show_date` must fall at least seven days after the current date, the curfew must be strictly later than doors, and doors must fall on the show date itself; any violation is rejected with `ERR_INVALID_SHOW_SCHEDULE` (HTTP 422). A new show is born in `HOLD_PENDING` with `hold_priority` set to `NONE`, `cancellation_reason` set to `NONE`, `weather_or_emergency_flag` false, `deal_id` unset, and `tickets_sold` and `gross_ticket_revenue_cents` at zero; the platform also creates the show's advance checklist with all six items false (§3.5). The show list supports optional filters `status`, `artist_id`, `room`, `show_date`, and `deal_id`.

Against a pending show, a `BookingAgent` places a date hold with a `priority` of `P1`, `P2`, or `COURTESY` and a `booked_by_agent_id` naming the placing agent. The platform stamps the hold `ACTIVE` and computes its `hold_expires_at_utc` from a fixed time-to-live ladder: a `P1` hold lives 48 hours, a `P2` hold 24 hours, and a `COURTESY` hold 12 hours. Priorities rank strictly — `P1` outranks `P2`, which outranks `COURTESY`. The date-hold ledger can be listed across shows with optional filters `show_id`, `booked_by_agent_id`, `status`, and `priority`.

Competition is formalized through the challenge. A `BookingAgent` challenges another agent's `ACTIVE` hold on the same room and date by supplying a `challenger_agent_id` and a `challenger_priority`. Three conditions must hold: the target hold is `ACTIVE`, the challenger is a different agent than the target hold's `booked_by_agent_id`, and the challenger's priority is strictly higher than the target's — a `P2` cannot challenge another `P2`. A challenge whose priority is not strictly higher is rejected with `ERR_CHALLENGE_PRIORITY_TOO_LOW` (HTTP 422). A successful challenge flips the target hold from `ACTIVE` to `CHALLENGED`, sets its `challenge_window_ends_at_utc` to exactly 24 hours from the challenge, and creates a brand-new `ACTIVE` hold for the challenger at the challenger_priority with its own freshly computed expiry.

Confirmation ends the contest, and it comes in two flavors. An unchallenged `ACTIVE` hold may be confirmed by the agent that placed it — the caller's identity must equal the hold's `booked_by_agent_id` — provided the confirmation lands strictly before the hold's `hold_expires_at_utc` and no competing hold blocks it: no other `ACTIVE` hold on the same room and date may hold a strictly higher priority, and among equal-priority `ACTIVE` competitors the earliest-created hold wins. That first-created tie-break is the only sanctioned one; resource ids are never used to break ties. A challenged hold plays by different rules: a `CHALLENGED` hold may be confirmed only by its original holder and only strictly before `challenge_window_ends_at_utc`, but the priority comparison is bypassed entirely — the 24-hour window is the original holder's protected opportunity to confirm regardless of the challenger's priority. Confirming at or past the applicable deadline is rejected with `ERR_HOLD_EXPIRED` (HTTP 422); confirming a hold that is not in the `ACTIVE` or `CHALLENGED` from-state is rejected with `ERR_INVALID_STATE` (HTTP 409). Confirmation is one of the four versioned writes of §2.6, so the request must carry `expected_show_version` matching the show's current `version`, with a mismatch rejected as `ERR_STALE_VERSION` (HTTP 412).

A successful confirmation does four things as one cascade: the hold becomes `CONFIRMED`; the show moves from `HOLD_PENDING` to `CONFIRMED` and its `hold_priority` is copied from the confirmed hold's `priority`; every other date hold on the same room and date that is `ACTIVE` or `CHALLENGED` is released to `RELEASED`; and the show's `version` increments by one. Between challenge and confirmation, either side can stand down: the agent that placed a hold may release it, moving it from `ACTIVE` to `RELEASED` or from `CHALLENGED` to `RELEASED`, again only when the caller is the hold's `booked_by_agent_id`. Holds that simply run out of time lapse without any agent action: an `ACTIVE` hold expires when the house clock reaches its `hold_expires_at_utc`, and a `CHALLENGED` hold expires when the clock reaches its `challenge_window_ends_at_utc`. Expiry is quiet on the show — it remains `HOLD_PENDING`, waiting for some other hold to confirm.

### 3.3. Negotiating the Deal: Offers, Counters, and the Accepted Snapshot

With a date held, the two sides negotiate. Either a `BookingAgent` or a `VenueManager` opens round one by creating an offer on the show, and every offer carries a complete commercial package: the `deal_kind` — one of `FLAT_GUARANTEE`, `DOOR_SPLIT`, or `VERSUS` — plus `guarantee_cents`, `artist_split_pct`, `versus_threshold_cents`, `expense_budget_cents`, `support_budget_cents`, `bar_split_pct`, and `merch_split_pct`. The platform stamps each offer with its `round_number`, one greater than the highest existing round on that show, or 1 for the first offer; it records the proposing side in `proposed_by_role` as `BOOKING_AGENT` or `VENUE_MANAGER` taken from the caller; and round 1's `supersedes_offer_id` is null. Offers can be listed with optional filters `show_id`, `status`, and `supersedes_offer_id`.

Deal terms are validated against the deal kind, and this check runs before the guarantee-floor check of the next paragraph. A `FLAT_GUARANTEE` or `VERSUS` offer must include a non-negative `guarantee_cents`; a `DOOR_SPLIT` or `VERSUS` offer must include an `artist_split_pct`; a `VERSUS` offer must include a `versus_threshold_cents` naming the door-revenue threshold above which the split applies. Ranges are enforced regardless of kind: `artist_split_pct` between 0.0 and 1.0 inclusive, `bar_split_pct` between 0.0 and 0.25 inclusive (the artist's share of net bar revenue), and `merch_split_pct` between 0.0 and 0.30 inclusive (the venue's share of gross merch). The `expense_budget_cents` caps recoupable house expenses for the show, and `support_budget_cents` caps total support-act payouts. Any missing kind-required field or out-of-range value is rejected with `ERR_INVALID_DEAL_TERMS` (HTTP 422). Only after terms are well-formed does the floor apply: for guarantee-bearing kinds, an offer whose `guarantee_cents` falls below the artist's `guarantee_floor_cents` is rejected with `ERR_GUARANTEE_BELOW_FLOOR` (HTTP 422). Both rules govern initial offers and counters alike.

Every offer is born `PENDING`, and the negotiation loop turns on one iron rule: the side that proposed an offer can never be the side that answers it. Countering, accepting, or rejecting requires the caller's role to differ from the offer's `proposed_by_role`; a matching role is rejected with `ERR_SELF_NEGOTIATION` (HTTP 422). A counter — allowed while the show is `HOLD_PENDING` or `CONFIRMED` — moves the answered offer from `PENDING` to `COUNTERED` and creates a fresh `PENDING` offer in one motion: its `round_number` is the answered offer's round plus one, its `proposed_by_role` is the countering side, and its `supersedes_offer_id` points at the offer it answers. A rejection moves the offer from `PENDING` to `REJECTED` with no further effect. The proposing side alone may withdraw its own offer, moving it from `PENDING` to `WITHDRAWN`; here the caller's role must equal `proposed_by_role`.

Acceptance is the moment the deal becomes real, and it is guarded more tightly than any other negotiation step: the offer must be `PENDING`, the show must be `CONFIRMED` — acceptance is impossible while the show is still `HOLD_PENDING`, even though counters are permitted there — the caller must be the opposite side, and the request must carry `expected_show_version` matching the show's current `version`, with a stale version rejected as `ERR_STALE_VERSION` (HTTP 412) per §2.6. On acceptance the offer becomes `ACCEPTED` and the platform mints a `Deal`: an `ACTIVE` snapshot copying the accepted offer's `offer_id` and every commercial term — `deal_kind`, `guarantee_cents`, `artist_split_pct`, `versus_threshold_cents`, `expense_budget_cents`, `support_budget_cents`, `bar_split_pct`, and `merch_split_pct` — so that later negotiation can never rewrite history. The show's `deal_id` is set to the new deal. Every other offer on the show still sitting in `PENDING` or `COUNTERED` is swept to `SUPERSEDED`. The show's `version` increments by one.

Acceptance also fixes the deposit economics, computed exactly once and never recomputed: `deposit_required_cents` is the accepted offer's `guarantee_cents` multiplied by the artist's `deposit_pct`, rounded half up to the cent, and it is immutable thereafter even if the artist's `deposit_pct` later changes. The wire deadline `deposit_due_by_utc` is set to fourteen days before the `show_date`. The deposit must not merely be initiated but fully completed by that deadline; the on-sale gate of §3.4 enforces the funded check, and if the deadline passes with `deposit_paid_cents` short of `deposit_required_cents`, the venue may treat the shortfall as an artist breach and cancel under the `ARTIST` terms of §3.9, retaining whatever partial deposit was paid.

A show carries at most one active deal, fetchable either through the show or by its own id, and deals can be listed with optional filters `show_id`, `offer_id`, and `status`. A deal's `status` flips from `ACTIVE` to `VOID` when its show is cancelled (§3.9).

### 3.4. Selling the Room: Tiers, On-Sale Gating, Roll-Up Allocation, and Refunds

A `Promoter` builds the ticket manifest tier by tier. Each tier carries a `tier_name` (GA, VIP, BALCONY, and the like), a strictly positive `face_price_cents`, a strictly positive `capacity`, and a `tier_order` that drives door scaling: lower numbers are cheaper and sell first at the door. Two constraints guard the manifest, both reported as `ERR_TIER_CAPACITY_EXCEEDED` (HTTP 422): the sum of tier capacities must not exceed the show's `total_capacity`, and `tier_order` must be unique within the show. Sales and refunds are tracked per tier in the computed counters `sold_count` and `refund_count`.

Going on sale is a gated promotion from `CONFIRMED` to `ON_SALE`, performed by a `Promoter`, and every gate must swing open together: the show must be `CONFIRMED`, a deal must be in place (`deal_id` set by an accepted offer), the deposit must have landed — `deposit_paid_cents` at least equal to `deposit_required_cents` — the house clock must have reached the show's `on_sale_at_utc`, and at least one ticket tier must exist. A short deposit or an early clock is rejected with `ERR_DEPOSIT_NOT_CLEARED` (HTTP 422); a wrong from-state draws `ERR_INVALID_STATE` (HTTP 409). This is one of the four versioned writes of §2.6, so `expected_show_version` is required and a stale version draws `ERR_STALE_VERSION` (HTTP 412). Success moves the show to `ON_SALE`, increments its `version` by one, and opens the box office: ticket sales are accepted only from this point forward, and attempts to record a sale before the show is on sale are rejected as an invalid state.

Selling tickets is where the tier ladder earns its keep. A `Promoter` sells by naming a `tier_id` — which must exist, else `ERR_NOT_FOUND` — and a `quantity` of at least one. Allocation fills from the requested tier first; any remainder rolls up to progressively higher `tier_order` tiers, always in ascending `tier_order` with `created_at` as the tie-break between equal orders, and each tier's portion is charged at that tier's own `face_price_cents`. The candidate pool is the requested tier plus every tier on the show with a strictly higher `tier_order`. If the total availability across the candidate pool falls short of the requested quantity, the entire sale is rejected with `ERR_INSUFFICIENT_TICKET_CAPACITY` (HTTP 422) — partial fills do not exist. A successful sale is recorded as a single `TicketSale` row whose `gross_amount_cents` is the composite sum across all tiers that filled it (for a single-tier fill, simply the quantity multiplied by the tier's face price), stamped with the server's `sold_at_utc`, born with `refund_status` `NONE`. Each contributing tier's `sold_count` rises by the number of seats it supplied, and the show's `tickets_sold` and `gross_ticket_revenue_cents` are recomputed. Sales ledgers can be listed with optional filters `tier_id` and `refund_status`, plus `show_id` across the cross-show listing.

Refunds unwind a sale exactly. A `Promoter` refunding a sale flips its `refund_status` from `NONE` to `REFUNDED`, decrements the tier's `sold_count` by the sale's `quantity`, increments the tier's `refund_count` by the same, and recomputes the show's `tickets_sold` and `gross_ticket_revenue_cents` so that refunded money disappears from every downstream calculation — the settlement waterfall of §3.7 counts only sales whose `refund_status` is still `NONE`.

### 3.5. Advancing the Production

Every show carries exactly one advance checklist, created alongside the show with all six items false. The six items are `hospitality_done` (hospitality rider received), `tech_done` (tech rider received and approved), `backline_done` (backline list confirmed), `production_requirements_done` (stage plot, input list, and lighting plot all received), `insurance_cert_received` (certificate of insurance on file), and `w9_received` (artist W-9 on file). A seventh, computed flag `all_complete` is true exactly when all six items are true.

A `ProductionManager` works the checklist while the show is `CONFIRMED` or `ON_SALE`, marking items complete or incomplete one at a time by naming the item in the path variable `item_name` — one of hospitality, tech, backline, production_requirements, insurance_cert, or w9; any other value fails path existence with `ERR_NOT_FOUND` as described in §2.9. Each toggle re-evaluates `all_complete` immediately. Operating on a show outside the `CONFIRMED` and `ON_SALE` states is rejected with `ERR_INVALID_STATE` (HTTP 409).

When every item stands complete, the `ProductionManager` completes the advance, moving the show from `ON_SALE` to `ADVANCED`; the transition requires `all_complete` to be true and rejects otherwise. From there the night takes over: once the house clock reaches the show's `doors_at_utc` while remaining strictly before `curfew_at_utc`, an `ADVANCED` show moves to `SHOW_NIGHT`, evaluated lazily on the next read per §2.7.

### 3.6. Support Acts, House Expenses, and Ancillary Revenue

A `Promoter` books support by naming the `artist_name`, an `agreed_fee_cents` that must be strictly positive, and a `buyout_fee_cents` that must sit within a fixed band — at least one half of the agreed fee and no more than the agreed fee itself. Support acts are born `CONFIRMED`, and the house keeps cumulative support spend inside the deal's `support_budget_cents`: the sum of buyout fees across acts already `BOUGHT_OUT` plus agreed fees across acts still `CONFIRMED` must not exceed the budget, checked both when an act is added and when an act is bought out. Violations of the fee band or the budget cap are rejected with `ERR_SUPPORT_BUDGET_EXCEEDED` (HTTP 422). Support-act lists can be filtered by `status`.

Two fates await a confirmed act under promoter control. A buyout — allowed while the show is `CONFIRMED`, `ON_SALE`, or `ADVANCED`, and subject to the same budget check — moves the act from `CONFIRMED` to `BOUGHT_OUT` and initiates a `SUPPORT_BUYOUT` wire for the `buyout_fee_cents`. Marking an act performed is a show-night action only: with the show in `SHOW_NIGHT`, the act moves from `CONFIRMED` to `PERFORMED` and a `SUPPORT_FEE` wire for the full `agreed_fee_cents` is initiated. Both wires start life `INITIATED` for the `Accountant` to work (§3.8), and each act's `paid_cents` accumulates as its support wires complete. The third fate — cancellation — arrives only as a cascade of §3.9.

House expenses enter through a `Promoter` or `VenueManager`, each receipt carrying a `category` — one of `SOUND`, `LIGHTS`, `BACKLINE`, `HOSPITALITY`, `SECURITY`, `MARKETING`, or `MISC` — a strictly positive `amount_cents`, a `receipt_reference` invoice number, and an `is_recoupable` flag that defaults to true; a receipt marked not recoupable is house-only and is never deducted from the door. The platform stamps `submitted_by_role` from the caller as `PROMOTER` or `VENUE_MANAGER`, and the receipt is born `PENDING`. Receipt lists can be filtered by `status` and `category`. A `VenueManager` alone adjudicates: approval requires the receipt still `PENDING` and the show in `CONFIRMED`, `ON_SALE`, `ADVANCED`, or `SHOW_NIGHT`, and moves the receipt to `APPROVED`; rejection requires a `rejection_reason` and moves it to `REJECTED`. Approving a receipt while a settlement draft exists recomputes the draft's `recoupable_expenses_cents` — but only a draft; a submitted settlement is frozen, per §3.7.

Recoupment follows a strict chronological discipline when the settlement runs. Only `APPROVED` receipts flagged recoupable participate, and they are applied oldest-first by `created_at` against the deal snapshot's `expense_budget_cents` — never the current offer's terms. Receipts fit whole until the cap is reached; the first receipt that would push the cumulative total over the cap is truncated so its recoupable portion lands exactly on the cap, and every later receipt recoups at zero. The settlement's `recoupable_expenses_cents` is that cumulative total — the full sum when under the cap, exactly the cap when over — and the per-receipt ordering matters whenever a per-receipt recoupment breakdown is reported.

Ancillary money — the bar and the merch table — is recorded by a `Promoter` or `VenueManager` as rows carrying a `kind` of `BAR` or `MERCH`, a strictly positive `gross_cents` for the night's receipts, and a non-negative `cost_cents`. For merch, the cost is the artist's own cost of goods and is deliberately not deducted when the venue's merch split is computed (§3.7). The platform stamps `recorded_by_role` from the caller and `recorded_at_utc` from the server. Ancillary rows can be listed with an optional `kind` filter.

### 3.7. Night-of Settlement: The Payout Waterfall, Submission, Approval, and Dispute

Each show has exactly one settlement, created by a `Promoter` and born in `DRAFT` with every computed field resolved by the payout waterfall. The waterfall runs again — from current show state — whenever a disputed settlement is returned to draft. All arithmetic is integer cents under §2.5's rounding rule: half-up rounding happens only at the explicit rounding steps named below, never on intermediate products.

The waterfall runs in this order. Gross ticket revenue is the sum of `gross_amount_cents` over the show's ticket sales whose `refund_status` is still `NONE`, snapshotted onto the settlement's `gross_ticket_revenue_cents`. Recoupable expenses follow §3.6's chronological cap discipline, landing in `recoupable_expenses_cents`. The `net_door_cents` is the gross minus recoupable expenses, floored at zero so a heavy expense night can never make the door negative.

The artist's door share then branches on the deal snapshot's `deal_kind`. Under `FLAT_GUARANTEE`, `artist_door_share_cents` is the deal's `guarantee_cents`, `guarantee_paid_cents` equals that guarantee, and `bonus_cents` is zero. Under `DOOR_SPLIT`, `artist_door_share_cents` is the net door multiplied by `artist_split_pct`, rounded half up; `guarantee_paid_cents` is zero and `bonus_cents` is zero. Under `VERSUS`, the deal pays the guarantee plus a marginal split of the net door above the threshold: the door-split component is the excess of `net_door_cents` over `versus_threshold_cents` — floored at zero — multiplied by `artist_split_pct` and rounded half up. The comparator is strictly greater than: when the net door exceeds the threshold, `artist_door_share_cents` is the guarantee plus that component, `guarantee_paid_cents` is the guarantee, and `bonus_cents` is the component; when the net door is equal to or below the threshold, there is no bonus at all — `artist_door_share_cents` and `guarantee_paid_cents` are both exactly the guarantee, and `bonus_cents` is zero. The split is a marginal rate on the increment above the threshold, never an average rate over the whole net door.

Ancillary shares come next. The bar share `bar_artist_share_cents` is the night's total bar gross minus total bar cost — floored at zero — multiplied by the deal's `bar_split_pct`, rounded half up. The merch share `merch_venue_share_cents` is the total merch gross multiplied by `merch_split_pct`, rounded half up, with the merch cost deliberately not deducted. Support obligations `support_payouts_cents` total the `paid_cents` across all of the show's support acts, covering both performed fees and buyouts. The `deposit_credit_cents` is the show's `deposit_paid_cents` — money the artist already holds, credited back against the payout. The `artist_total_due_cents` is the door share (which, under `VERSUS`, already includes the bonus) plus the bar share, minus the deposit credit, floored at zero. The house's own take, `venue_net_cents`, is the net door minus the artist's door share, minus support payouts, plus the merch venue share, plus whatever bar margin remains after the artist's bar share — the bar gross minus bar cost minus bar artist share, floored at zero.

A draft is provisional by construction: it reflects the show's current sales, receipts, ancillary rows, and support payouts, and mutating any of those inputs and returning the settlement to `DRAFT` recomputes every field. Submission freezes it. A `Promoter` submits only when the settlement is `DRAFT`, the show has reached `SHOW_NIGHT`, every expense receipt is in a terminal state (`APPROVED` or `REJECTED`), and every support act is terminal (`PERFORMED`, `BOUGHT_OUT`, or `CANCELLED`) — outstanding `PENDING` receipts or lingering `CONFIRMED` support acts are rejected with `ERR_SETTLEMENT_NOT_READY` (HTTP 422). Submission is one of the four versioned writes of §2.6: `expected_show_version` must match the show's current `version`, a stale version drawing `ERR_STALE_VERSION` (HTTP 412), because the submission pins `gross_ticket_revenue_cents` and `recoupable_expenses_cents` as of the observed show, and any refund, approval, or buyout landing in between invalidates the snapshot. A successful submission stamps `submitted_at_utc` with the current time, records the promoter's opaque id in `submitted_by_user_id`, moves the settlement to `SUBMITTED`, and increments the show's `version` by one. From this moment the settlement's computed fields are frozen: later expense approvals, refunds, or ancillary postings do not alter a `SUBMITTED` settlement — corrections must go through the dispute loop instead.

Approval belongs to the `Accountant`, and segregation of duties is enforced by identity: the approver's `X-User-ID` must differ from the settlement's `submitted_by_user_id`, and a match is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422). Approval records the accountant's opaque id in `approved_by_user_id`, moves the settlement from `SUBMITTED` to `APPROVED`, and — when `artist_total_due_cents` is positive — initiates an `ARTIST_BALANCE` wire for exactly that amount. The artist's side retains a formal objection path: a `BookingAgent` may dispute a `SUBMITTED` settlement, moving it to `DISPUTED`, and a `Promoter` may then return it to `DRAFT`, which recomputes every computed field from the show's current state and restarts the cycle.

The final step belongs to the wires. When the `ARTIST_BALANCE` wire for the settlement reaches `COMPLETED`, the settlement moves from `APPROVED` to `PAID`; and once the settlement is `PAID` and every wire with purpose `ARTIST_BALANCE`, `SUPPORT_FEE`, or `SUPPORT_BUYOUT` for the show stands `COMPLETED`, the show itself moves from `SHOW_NIGHT` to `SETTLED` and the artist's `total_settled_shows` ticks up by one. Settlements can be listed with optional filters `show_id` and `status`.

### 3.8. Moving the Money: Wire Transfers

Every dollar that moves, moves as a wire transfer, and every wire is worked by the `Accountant`. A wire carries a `purpose` — one of `ARTIST_DEPOSIT`, `ARTIST_BALANCE`, `SUPPORT_FEE`, `SUPPORT_BUYOUT`, or `REFUND_TO_VENUE` — a strictly positive `amount_cents`, and exactly the references its purpose implies: artist-bound purposes carry a `recipient_artist_id` naming the artist entity and leave `support_act_id` null; support purposes carry a `support_act_id` and leave `recipient_artist_id` null; an `ARTIST_BALANCE` wire additionally carries the `settlement_id` of the settlement it pays, which is null for every other purpose. Referenced artists, support acts, and settlements must exist, else the create fails existence checking with `ERR_NOT_FOUND`. Wire amounts are held to their canonical sources and mismatches are rejected with `ERR_WIRE_AMOUNT_MISMATCH` (HTTP 422): an `ARTIST_BALANCE` wire must equal the settlement's `artist_total_due_cents`, a `SUPPORT_FEE` wire must equal the act's `agreed_fee_cents`, and a `SUPPORT_BUYOUT` wire must equal the act's `buyout_fee_cents`. Every wire records `initiated_by_role` — always `ACCOUNTANT` — and a server-stamped `initiated_at_utc`, and is born `INITIATED`. Wire ledgers can be listed with optional filters `purpose`, `status`, `recipient_artist_id`, `support_act_id`, and `settlement_id`.

Many wires are born automatically at the moments §3.6, §3.7, and §3.9 describe: settlement approval initiates the `ARTIST_BALANCE` wire; marking a support act performed initiates its `SUPPORT_FEE` wire; a support buyout initiates its `SUPPORT_BUYOUT` wire; and cancellation initiates kill-fee and refund wires per policy. The `Accountant` may also initiate wires directly — the artist's `ARTIST_DEPOSIT` wires arrive this way — subject to the same amount-matching rules.

Completing a wire, from `INITIATED` to `COMPLETED`, stamps `completed_at_utc` and posts the money to its ledger: an `ARTIST_DEPOSIT` completion adds the amount to the show's `deposit_paid_cents`; an `ARTIST_BALANCE` completion moves its settlement to `PAID` and, when every support wire is also `COMPLETED`, lets the show settle per §3.7; a `SUPPORT_FEE` or `SUPPORT_BUYOUT` completion adds the amount to that act's `paid_cents`. A wire that cannot be completed is marked `FAILED` with a mandatory `failure_reason`; a failed wire can be retried, returning from `FAILED` to `INITIATED` with its `failure_reason` cleared. One special unwind exists for cancelled shows: a `COMPLETED` wire whose purpose is `ARTIST_DEPOSIT` may be marked `RETURNED` when the show is `CANCELLED`, subtracting the amount back out of the show's `deposit_paid_cents`. Every one of these transitions rejects a wire in the wrong from-state with `ERR_INVALID_STATE` (HTTP 409), and a wire already in a terminal state with no defined transition draws `ERR_ALREADY_TERMINAL` (HTTP 409).

### 3.9. Cancellation, Postponement, and Force Majeure

A show can be cancelled by a `BookingAgent`, a `VenueManager`, or a `Promoter` at any point while it stands `CONFIRMED`, `ON_SALE`, or `ADVANCED`, and a cancellation always declares a `reason` — one of `ARTIST`, `VENUE`, `FORCE_MAJEURE`, or `LOW_TICKET_SALES` — which is recorded both on the show's `cancellation_reason` and on the persisted `CancellationEvent`. Cancelling from any other state is rejected with `ERR_INVALID_STATE` (HTTP 409). The low-sales exit has an extra gate, evaluated before the cascade runs: `LOW_TICKET_SALES` is valid only while the show is `ON_SALE` and the show's `tickets_sold` is strictly below thirty percent of `total_capacity` rounded up to the next whole number; otherwise the cancellation is rejected with `ERR_LOW_SALES_THRESHOLD_NOT_MET` (HTTP 422).

The event record captures the full financial exposure in computed fields. Its `declared_by_role` is stamped from the caller as `BOOKING_AGENT`, `VENUE_MANAGER`, or `PROMOTER`, and `declared_at_utc` is server-stamped. The `days_before_show` is the whole number of calendar days between the declaration date and the show date, rounded down and never negative. The artist penalty applies only when the reason is `ARTIST`, and it slides with notice: cancelling at least sixty days out carries no penalty; at least thirty but fewer than sixty days costs twenty-five percent of the deal's guarantee; at least fourteen but fewer than thirty costs fifty percent; at least seven but fewer than fourteen costs seventy-five percent; and fewer than seven days costs the full guarantee. The resulting `artist_penalty_pct` is recorded, and `artist_penalty_cents` is the guarantee multiplied by that percentage, rounded half up. For every other reason the penalty percentage and amount are both zero.

Deposit handling follows the reason. Under `ARTIST`, the deposit stays with the artist and `deposit_refundable_cents` is zero; the artist forfeits the lesser of the deposit actually paid and the penalty, and any penalty above the deposit remains owed by the artist but is not auto-collected. Under `VENUE`, the deposit likewise stays with the artist, nothing is refundable, and the venue owes the artist the full guarantee as a kill fee regardless of how many days remain. Under `FORCE_MAJEURE`, no penalties run in either direction, the full `deposit_paid_cents` becomes refundable to the venue — `deposit_refundable_cents` equals the paid amount — and the show's `weather_or_emergency_flag` is set. Under `LOW_TICKET_SALES`, again no penalties run, the full deposit paid is refundable to the venue, and the venue owes the artist one half of the guarantee as a kill fee. Support kill fees apply under `ARTIST`, `VENUE`, and `LOW_TICKET_SALES`: each support act still `CONFIRMED` at the moment of cancellation earns one half of its `agreed_fee_cents`, rounded half up, and the `support_kill_fee_cents` is their sum. Under `FORCE_MAJEURE` there are no support kill fees at all.

The cancellation then cascades through the night in one motion. Every ticket sale not already refunded is refunded — `refund_status` moves from `NONE` to `REFUNDED` — and the show's `tickets_sold` and revenue counters are recomputed. Every `CONFIRMED` support act moves to `CANCELLED`, and for each of them a `SUPPORT_BUYOUT` wire for the kill fee is initiated when the reason is `ARTIST`, `VENUE`, or `LOW_TICKET_SALES`; a `FORCE_MAJEURE` cancellation initiates none. When the show holds a positive paid deposit and the reason is `ARTIST` or `FORCE_MAJEURE`, a `REFUND_TO_VENUE` wire is initiated for the refundable portion computed above — zero under `ARTIST`, the full paid amount under `FORCE_MAJEURE`. The show's deal is voided, its `status` moving from `ACTIVE` to `VOID`. The show itself lands in `CANCELLED`, a terminal state.

Postponement is the gentler exit, and it belongs to the `VenueManager` alone. A show in `CONFIRMED` or `ON_SALE` may be postponed by supplying a `new_show_date` strictly later than the current `show_date`, along with the successor's `new_doors_at_utc` and `new_curfew_at_utc`. The existing show moves to `POSTPONED`, and a brand-new show is created for the same artist on the new dates, born in `HOLD_PENDING` and ready for its own hold contest. The old show's ticket sales are not carried over — they are refunded at postpone time rather than transferred, and the successor starts with an empty house while clients re-book. A postponed show can still be cancelled afterward by a `VenueManager`; that cancellation records its event like any other but issues no further ticket refunds, because the tickets were already refunded when the show was postponed.

## 4. Endpoint Definitions

All endpoints live under the API root. Creating a new resource answers HTTP 201; reads, modifications, and state-transition actions on existing resources answer HTTP 200. Readers should reconstruct each endpoint's request payload and side effects from the workflow narratives of §3 — the table below is an index, not a schema.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /artists | Create an Artist | VenueManager |
| GET | /artists/{id} | Fetch an Artist by id | VenueManager, BookingAgent, Promoter, Accountant, ProductionManager |
| GET | /artists | List Artists | VenueManager, BookingAgent, Promoter, Accountant, ProductionManager |
| POST | /booking-agents | Create a BookingAgent | VenueManager |
| GET | /booking-agents/{id} | Fetch a BookingAgent | VenueManager, BookingAgent, Promoter |
| POST | /shows | Create a Show (status HOLD_PENDING, hold_priority NONE) | BookingAgent, VenueManager |
| GET | /shows/{id} | Fetch a Show | VenueManager, BookingAgent, Promoter, Accountant, ProductionManager |
| GET | /shows | List Shows | VenueManager, BookingAgent, Promoter, Accountant, ProductionManager |
| GET | /date-holds/{id} | Fetch a DateHold by id | VenueManager, BookingAgent, Promoter |
| GET | /date-holds | List DateHolds across shows (filtered) | VenueManager, BookingAgent, Promoter |
| POST | /shows/{id}/date-holds | Place a DateHold on a Show | BookingAgent |
| GET | /shows/{id}/date-holds | List DateHolds for a Show | VenueManager, BookingAgent, Promoter |
| GET | /shows/{id}/date-holds/{hold_id} | Fetch a DateHold | VenueManager, BookingAgent, Promoter |
| POST | /shows/{id}/date-holds/{hold_id}/challenge | Challenge an ACTIVE DateHold with a higher-priority hold | BookingAgent |
| POST | /shows/{id}/date-holds/{hold_id}/confirm | Confirm a DateHold (OCC on Show.version) | BookingAgent |
| POST | /shows/{id}/date-holds/{hold_id}/release | Release a DateHold | BookingAgent |
| GET | /offers/{id} | Fetch an Offer by id | VenueManager, BookingAgent, Promoter |
| GET | /offers | List Offers across shows (filtered) | VenueManager, BookingAgent, Promoter |
| POST | /shows/{id}/offers | Create an Offer (round 1 from agent or manager) | BookingAgent, VenueManager |
| GET | /shows/{id}/offers | List Offers for a Show | VenueManager, BookingAgent, Promoter |
| GET | /shows/{id}/offers/{offer_id} | Fetch an Offer | VenueManager, BookingAgent, Promoter |
| POST | /shows/{id}/offers/{offer_id}/counter | Counter an Offer (creates a new PENDING offer) | BookingAgent, VenueManager |
| POST | /shows/{id}/offers/{offer_id}/accept | Accept an Offer (OCC on Show.version) | BookingAgent, VenueManager |
| POST | /shows/{id}/offers/{offer_id}/reject | Reject an Offer | BookingAgent, VenueManager |
| POST | /shows/{id}/offers/{offer_id}/withdraw | Withdraw an Offer (same role as proposer) | BookingAgent, VenueManager |
| GET | /shows/{id}/deal | Fetch the ACTIVE Deal for a Show | VenueManager, BookingAgent, Promoter, Accountant |
| GET | /deals/{id} | Fetch a Deal by id | VenueManager, BookingAgent, Promoter, Accountant |
| GET | /deals | List Deals (filtered) | VenueManager, BookingAgent, Promoter, Accountant |
| POST | /shows/{id}/ticket-tiers | Create a TicketTier | Promoter |
| GET | /shows/{id}/ticket-tiers | List TicketTiers for a Show | VenueManager, BookingAgent, Promoter |
| GET | /shows/{id}/ticket-tiers/{tier_id} | Fetch a TicketTier | VenueManager, BookingAgent, Promoter |
| POST | /shows/{id}/on-sale | Move Show CONFIRMED to ON_SALE (OCC on Show.version) | Promoter |
| GET | /ticket-sales/{id} | Fetch a TicketSale by id | VenueManager, Promoter, Accountant |
| GET | /ticket-sales | List TicketSales across shows (filtered) | VenueManager, Promoter, Accountant |
| POST | /shows/{id}/ticket-sales | Sell tickets (with tier roll-up allocation) | Promoter |
| GET | /shows/{id}/ticket-sales | List TicketSales for a Show | VenueManager, Promoter, Accountant |
| GET | /shows/{id}/ticket-sales/{sale_id} | Fetch a TicketSale | VenueManager, Promoter, Accountant |
| POST | /shows/{id}/ticket-sales/{sale_id}/refund | Refund a TicketSale (sets refund_status REFUNDED) | Promoter |
| GET | /advance-checklists/{id} | Fetch an AdvanceChecklist by id | VenueManager, ProductionManager, Promoter |
| GET | /advance-checklists | List AdvanceChecklists (filtered) | VenueManager, ProductionManager, Promoter |
| GET | /shows/{id}/advance | Fetch the AdvanceChecklist for a Show | VenueManager, ProductionManager, Promoter |
| POST | /shows/{id}/advance/items/{item_name}/complete | Mark an advance item complete | ProductionManager |
| POST | /shows/{id}/advance/items/{item_name}/uncomplete | Mark an advance item incomplete | ProductionManager |
| POST | /shows/{id}/advance/complete | Move Show ON_SALE to ADVANCED (requires all_complete) | ProductionManager |
| POST | /shows/{id}/support-acts | Add a SupportAct | Promoter |
| GET | /shows/{id}/support-acts | List SupportActs for a Show | VenueManager, Promoter, Accountant, BookingAgent |
| GET | /shows/{id}/support-acts/{support_act_id} | Fetch a SupportAct | VenueManager, Promoter, Accountant, BookingAgent |
| POST | /shows/{id}/support-acts/{support_act_id}/buyout | Buy out a SupportAct (transitions to BOUGHT_OUT, initiates wire) | Promoter |
| POST | /shows/{id}/support-acts/{support_act_id}/mark-performed | Mark SupportAct as performed (show night) | Promoter |
| POST | /shows/{id}/expense-receipts | Submit an ExpenseReceipt | Promoter, VenueManager |
| GET | /shows/{id}/expense-receipts | List ExpenseReceipts for a Show | VenueManager, Promoter, Accountant |
| GET | /shows/{id}/expense-receipts/{receipt_id} | Fetch an ExpenseReceipt | VenueManager, Promoter, Accountant |
| POST | /shows/{id}/expense-receipts/{receipt_id}/approve | Approve an ExpenseReceipt | VenueManager |
| POST | /shows/{id}/expense-receipts/{receipt_id}/reject | Reject an ExpenseReceipt | VenueManager |
| POST | /shows/{id}/ancillary-revenues | Record BAR or MERCH revenue | Promoter, VenueManager |
| GET | /shows/{id}/ancillary-revenues | List AncillaryRevenue rows for a Show | VenueManager, Promoter, Accountant |
| GET | /settlements/{id} | Fetch a Settlement by id | VenueManager, Promoter, Accountant, BookingAgent |
| GET | /settlements | List Settlements (filtered) | VenueManager, Promoter, Accountant, BookingAgent |
| POST | /shows/{id}/settlement | Create the Settlement in DRAFT (computes all fields) | Promoter |
| GET | /shows/{id}/settlement | Fetch the Settlement for a Show (1:1) | VenueManager, Promoter, Accountant, BookingAgent |
| POST | /shows/{id}/settlement/submit | Submit Settlement (OCC on Show.version) | Promoter |
| POST | /shows/{id}/settlement/approve | Approve Settlement (Accountant; segregation of duties) | Accountant |
| POST | /shows/{id}/settlement/dispute | Dispute a SUBMITTED Settlement | BookingAgent |
| POST | /shows/{id}/settlement/return-to-draft | Return a DISPUTED Settlement to DRAFT (recompute) | Promoter |
| GET | /wire-transfers/{id} | Fetch a WireTransfer by id | VenueManager, Promoter, Accountant |
| GET | /wire-transfers | List WireTransfers across shows (filtered) | VenueManager, Promoter, Accountant |
| POST | /shows/{id}/wire-transfers | Initiate a WireTransfer | Accountant |
| GET | /shows/{id}/wire-transfers | List WireTransfers for a Show | VenueManager, Promoter, Accountant |
| GET | /shows/{id}/wire-transfers/{wire_id} | Fetch a WireTransfer | VenueManager, Promoter, Accountant |
| POST | /shows/{id}/wire-transfers/{wire_id}/complete | Mark WireTransfer COMPLETED | Accountant |
| POST | /shows/{id}/wire-transfers/{wire_id}/fail | Mark WireTransfer FAILED | Accountant |
| POST | /shows/{id}/wire-transfers/{wire_id}/retry | Retry a FAILED WireTransfer | Accountant |
| POST | /shows/{id}/wire-transfers/{wire_id}/mark-returned | Mark a COMPLETED ARTIST_DEPOSIT wire as RETURNED (on cancelled shows) | Accountant |
| POST | /shows/{id}/cancel | Cancel a Show (all branches) | BookingAgent, VenueManager, Promoter |
| GET | /shows/{id}/cancellation-events | List CancellationEvents for a Show | VenueManager, BookingAgent, Promoter, Accountant |
| POST | /shows/{id}/postpone | Postpone a Show to a new date (creates new Show) | VenueManager |
| POST | /_clock/set_current_utc | Set the server's logical clock (startup default 2026-08-01T00:00:00Z) | VenueManager |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows that raise them in §2 and §3; this table is only an index of identifiers to HTTP statuses.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_ALREADY_TERMINAL | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_SHOW_SCHEDULE | 422 |
| ERR_INVALID_DEAL_TERMS | 422 |
| ERR_GUARANTEE_BELOW_FLOOR | 422 |
| ERR_SELF_NEGOTIATION | 422 |
| ERR_HOLD_EXPIRED | 422 |
| ERR_CHALLENGE_PRIORITY_TOO_LOW | 422 |
| ERR_DEPOSIT_NOT_CLEARED | 422 |
| ERR_LOW_SALES_THRESHOLD_NOT_MET | 422 |
| ERR_TIER_CAPACITY_EXCEEDED | 422 |
| ERR_INSUFFICIENT_TICKET_CAPACITY | 422 |
| ERR_SUPPORT_BUDGET_EXCEEDED | 422 |
| ERR_WIRE_AMOUNT_MISMATCH | 422 |
| ERR_SETTLEMENT_NOT_READY | 422 |
| ERR_SEGREGATION_OF_DUTIES | 422 |

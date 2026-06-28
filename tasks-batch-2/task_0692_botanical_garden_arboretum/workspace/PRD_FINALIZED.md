# Botanical Garden / Arboretum — Membership & Admission Platform — Product Requirements Document

## 1. Introduction

A botanical garden or arboretum operates as far more than a turnstile. On any given day it must admit timed-entry visitors against a finite gate capacity, honor the free-admission privileges of its members and the discounted privileges of reciprocal members visiting from sister gardens, sell tickets to special exhibits, enroll children in summer camps and adults in horticulture workshops, rent its conservatory halls for weddings, and steward the gifts that flow into its conservancy endowment. This platform is the system of record behind all of those activities. It models each garden as an independent tenant whose catalog — membership plans, timed-entry slots, program sessions, and rentable venues — and whose transactional records — memberships, reservations, tickets, registrations, rentals, and donations — never bleed across tenant boundaries.

The platform's central tension is between *allocation* and *pricing*. Gate capacity, session seats, and venue calendars are scarce resources that are competed for, held, committed, and released; the same reservation that holds three gate heads must also be priced, and that price depends on whether the visitor is a member, a reciprocal guest, or a walk-up paying full general admission. Membership itself is a living thing with a yearly cycle: it is joined, activated, renewed (crediting the unused remainder of the prior term), allowed to lapse, reinstated, or cancelled outright — and when it lapses or cancels, the reservations and registrations that depended on it must unwind in a controlled cascade. This document specifies every entity, every state transition, every price calculation, and every guardrail that the implementation must honor so that all of these subsystems remain mutually consistent under concurrent use.

The audience is the engineering team building the REST API. Domain rules are stated first and their mechanical consequences second; where a number matters, it is given exactly, and where an ordering matters, the ordering is pinned.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the platform must carry two headers: `X-User-ID`, identifying the calling principal, and `X-User-Role`, naming the principal's role. If either header is absent, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing. When both headers are present but the named role is not permitted to perform the requested operation under the authorization matrix in Section 4, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

There are exactly five roles, spelled precisely as follows: `GardenAdmin`, `GardenStaff`, `RentalCoordinator`, `DevelopmentOfficer`, and `Visitor`.

The first four are operator roles whose identity is opaque. When `X-User-Role` is `GardenAdmin`, `GardenStaff`, `RentalCoordinator`, or `DevelopmentOfficer`, the `X-User-ID` value is an opaque operator identifier that is not tied to any persisted entity; the server may record it for audit but never compares it to any entity's `id`. `GardenAdmin` is the garden operator who creates gardens, builds catalogs, and exercises administrative overrides. `GardenStaff` are gate and registrar personnel who check visitors in and perform transactions on behalf of visitors. `RentalCoordinator` manages venues and the rental approval lifecycle. `DevelopmentOfficer` manages donations and the conservancy match campaign.

`Visitor` is an entity-backed role. When `X-User-Role` is `Visitor`, `X-User-ID` is the `id` of the acting `Membership` — specifically the membership held by the account holder named in `primary_member_name`. Ownership checks on any resource that references a `Membership` compare the resource's `membership_id` to `X-User-ID`. Concretely, when a `Visitor` attempts a mutation on a member-owned resource — cancelling a reservation, renewing or cancelling or reinstating a membership, withdrawing a registration, or cancelling a rental — the server resolves the owning membership of that resource and confirms that its `id` equals `X-User-ID`; if it does not, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). For a resource that itself *is* a membership, the owning membership is the resource. For a reservation, registration, or rental, the owning membership is the one referenced by its `membership_id`. The ownership comparison applies only to resources that actually reference a `Membership`: a reservation, registration, or rental whose `membership_id` is empty (a non-member resource) is not member-owned, so the ownership check is skipped for it and a `Visitor` permitted by role may mutate it regardless of `X-User-ID`. Operator roles bypass the ownership comparison because their identity is opaque.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10 when omitted, must be at least 1, and must not exceed 100. The `offset` defaults to 0 and must be at least 0. Results are always returned sorted by `created_at` in ascending order — that is, the oldest record appears first. The `meta` block of a list response carries the `limit` and `offset` in effect, the `total_count` of records matching the filter before pagination is applied, and `has_more`, a boolean that is true when records remain beyond the current page.

### 2.4. Common Resource Properties and the Logical Clock

Every persisted resource carries a server-minted `id`, which is a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. All entities in this system additionally carry an `updated_at` timestamp, refreshed on every mutation, and an integer `version` that begins at 1 and increments by exactly one each time the resource is mutated. The `version` field is the basis of the optimistic-concurrency mechanism described in Section 2.8.

Because admission, membership terms, sessions, and rentals all turn on the passage of time, the platform runs on a *logical clock* rather than wall-clock time. At server startup the clock reads exactly `2026-04-01T00:00:00Z`, and before any explicit set it remains at this default and never falls back to the host's wall-clock. A privileged test-driving capability advances the clock to a supplied instant; advancing the clock is also the system's heartbeat for time-driven sweeps (Section 2.5). All "now" comparisons throughout this document — slot windows, term expiry, renewal windows, rental windows — are evaluated against the logical clock.

### 2.5. Time-Driven Sweeps and Cascading Side Effects

Whenever the logical clock is advanced, the platform performs two sweeps in the same operation, and the operation reports the `now` it advanced to along with the ids of resources it transitioned.

The first sweep expires stale holds. Any reservation still in `HELD` status whose referenced time slot has already ended — that is, the new clock value has reached or passed the slot's `ends_at` — transitions to `EXPIRED`. Expiring a reservation releases its `party_size` from the slot's `held_count`; if that release brings `held_count` below the slot's `capacity` and the slot was `CLOSED`, the slot reopens to `OPEN`.

The second sweep lapses memberships. Any membership in `ACTIVE` status whose `auto_renew` is false and whose `term_end` has been reached or passed by the new clock value transitions to `LAPSED`. Lapsing is not a quiet status flip; it triggers a cascade. Every `HELD` reservation owned by the lapsing membership whose slot has not yet started — its slot start is at or after the current clock — is cancelled to `CANCELLED`, releasing that reservation's heads from the slot's `held_count` (which may itself flip a `CLOSED` slot back to `OPEN`). Every `ENROLLED` future registration owned by the lapsing membership is withdrawn to `WITHDRAWN`, which decrements the session's `enrolled_count` and, in turn, promotes that session's head waitlister. Finally the membership's `guest_passes_remaining` is set to 0. The same cascade is available administratively through a forced-lapse capability, which produces identical effects.

A unifying rule governs these cascades: when one operation mutates several entities, *every* affected entity has its `updated_at` refreshed and its `version` incremented, not merely the entity the caller named. A reservation cancellation that releases capacity bumps the slot's `version`; a withdrawal that promotes a waitlister bumps both the session's `version` and the promoted registration's `version`.

### 2.6. Money, Counts, and Rounding

All monetary amounts in this system are expressed as integer cents, and all stored money fields are whole-cent integers. Where a calculation produces a fractional cent — applying a percentage discount, prorating a daily value — the result is rounded half-up to the nearest whole cent (a value exactly halfway between two cents rounds up). Several calculations pin the *order* in which rounding happens relative to multiplication; those orderings are stated explicitly with each calculation in Section 3 and must be followed, because rounding a per-unit price before multiplying yields a different total than summing first and rounding once. Counts — heads, tickets, guest passes, enrolled seats, days, hours — are whole integers; where a partial unit of time must be converted to a whole count, the rule (round up versus round down) is given at the calculation.

### 2.7. Tenant Isolation and Nested Reference Validation

Each garden is an isolated tenant root. Every other resource carries a `garden_id` binding it to its garden, and every cross-resource reference a request makes — a reservation's `time_slot_id` and `membership_id`, a registration's `program_session_id`, a rental's `venue_id`, a donation's `membership_id` — must point at a resource belonging to the *same* garden named by the request's `garden_id`. A reference whose target lives in a different garden is rejected with `ERR_CROSS_GARDEN_REFERENCE` (HTTP 422).

References are validated left to right: the garden named by `garden_id` is checked for existence first, then each referenced resource, and any resource that does not exist yields `ERR_NOT_FOUND` (HTTP 404). Existence (404) is evaluated before same-garden membership (422). A read against a resource id that does not exist likewise yields `ERR_NOT_FOUND`. Malformed request bodies — a missing required field, a value of the wrong type, or an enum value outside the permitted set — are rejected with `ERR_VALIDATION` (HTTP 422).

### 2.8. Optimistic Concurrency on Membership

A reservation that draws on a membership's privileges — claiming free member heads or spending guest passes — must be protected against acting on a stale view of that membership's guest-pass balance. The create-reservation operation therefore participates in optimistic concurrency control against the attached `Membership`. When a reservation is created with a non-empty `membership_id`, the request must carry `expected_membership_version`, and this field is non-optional in that case: it must equal the target membership's current `version`. Each reservation that spends guest passes or claims member heads against a membership increments that membership's `version` by one, as does a renewal that resets the guest-pass balance. If, between the moment the client last read the membership and the moment it submits the create, another writer has advanced the membership's `version`, the supplied `expected_membership_version` no longer matches, and the create is rejected with `ERR_STALE_MEMBERSHIP_VERSION` (HTTP 412). This prevents two reservations from each believing they hold the same guest-pass allotment. A reservation created with an empty `membership_id` is a non-member reservation and carries no version field; no other endpoint in the system takes a version field.

### 2.9. Validation Ordering

When several checks could fail a single request, they are evaluated in a fixed priority so that the returned `error_id` is deterministic. The order is: authentication first (`ERR_UNAUTHENTICATED`), then role permission (`ERR_FORBIDDEN_ROLE`), then resource ownership for entity-backed visitors (`ERR_NOT_RESOURCE_OWNER`), then existence of all referenced resources (`ERR_NOT_FOUND`), then same-garden referential integrity (`ERR_CROSS_GARDEN_REFERENCE`), then the target's state validity for the requested transition (`ERR_INVALID_STATE`), then the optimistic-concurrency version check (`ERR_STALE_MEMBERSHIP_VERSION`), then the membership-active cross-entity gate (`ERR_MEMBERSHIP_NOT_ACTIVE`), then time-window well-formedness (`ERR_INVALID_WINDOW`), then the household-cap check (`ERR_HOUSEHOLD_CAP_EXCEEDED`), then guest-pass sufficiency (`ERR_INSUFFICIENT_GUEST_PASSES`), then reciprocal eligibility (`ERR_RECIPROCAL_NOT_ELIGIBLE`), then venue overlap (`ERR_VENUE_DOUBLE_BOOKED`), then slot capacity (`ERR_SLOT_CAPACITY_EXCEEDED`), and finally session availability (`ERR_SESSION_CLOSED`). An earlier check that fires masks every later one; for example, a request that is both forbidden by role and references a missing resource returns `ERR_FORBIDDEN_ROLE`, never `ERR_NOT_FOUND`. Each individual endpoint applies only the subset of these checks relevant to it, but always in this relative order.

## 3. Business Logic & Workflows

### 3.1. Gardens and the Catalog

A `GardenAdmin` brings a garden into existence by supplying its display `name` and, optionally, the parameters that govern its members' privileges. The `timezone` is an IANA zone used for local-day math on slots and sessions and defaults to `America/New_York`. The `reciprocal_network_code` names the reciprocal-garden network this garden belongs to — for example a horticultural society code — and defaults to the empty string, which signifies membership in no network at all. The `reciprocal_discount_pct` is the fraction off general admission honored for reciprocal members visiting from *other* gardens in the same network and defaults to one-half. The `household_member_cap` is the maximum number of named household members a household-tier membership may carry, excluding the primary member, and defaults to 2. Two activation-time grants are configured here as well: `guest_pass_grant_household` (defaulting to 4) and `guest_pass_grant_patron` (defaulting to 8), the guest-pass allotments handed to household-tier and patron-tier memberships respectively.

The membership catalog is a set of plans, each created by a `GardenAdmin` against a garden's `garden_id` for a specific `tier`, which is one of `INDIVIDUAL`, `HOUSEHOLD`, or `PATRON`. A plan fixes the `annual_fee_cents` (which must be zero or positive), a boolean `admission_included` that defaults to true and grants the plan's named members free general admission, the `event_discount_pct` members of this tier receive off special-exhibit ticket prices (defaulting to one-fifth), the `program_discount_pct` they receive off education tuition (defaulting to one-tenth), and an `active` flag, defaulting to true, that controls whether new memberships may be created or reinstated against the plan. Plans may be listed and filtered by `garden_id` and by `tier`.

`GardenAdmin` or `GardenStaff` populate the visit catalog. A time slot is created with its `garden_id`, an inclusive window start `starts_at`, an exclusive window end `ends_at` that must be strictly later than `starts_at`, a total head `capacity` of at least 1, and the per-head general-admission price `ga_price_cents` charged to non-members (zero or positive). A new slot opens with its `status` at `OPEN` and `held_count` at 0; the `held_count` tracks heads held by non-terminal reservations — those in `HELD` or `CHECKED_IN`. A program session is created with its `garden_id`, a `title`, a start instant `starts_at`, an enrollment `capacity` of at least 1, and a per-registration `tuition_cents` (zero or positive); it opens `OPEN` with `enrolled_count` at 0. A venue is created with its `garden_id`, a `name`, an `hourly_rate_cents` rental rate (zero or positive), a `buffer_minutes` turnover gap that must separate two bookings and defaults to 60, and a `member_rental_discount_pct` granted to patron-tier members on the rental subtotal, defaulting to fifteen-hundredths. A `GardenStaff` member may close a session, transitioning its `status` from `OPEN` to `CLOSED`, after which new enrollments are refused; existing `ENROLLED` and `WAITLISTED` registrations are unaffected.

### 3.2. The Membership Lifecycle

A membership is created — by a `Visitor` for their own account or by `GardenStaff` on a visitor's behalf — against a garden's `garden_id` and a plan's `plan_id`, naming the `primary_member_name` and, for a household plan, the `household_member_names` array. The optional `auto_renew` flag defaults to false. A freshly created membership lands in `PENDING` status with `guest_passes_remaining` at 0, `paid_total_cents` at 0, and `renewal_count` at 0; its `term_start` and `term_end` are not yet set. The household roster is constrained: for a `HOUSEHOLD` plan the number of entries in `household_member_names` must not exceed the garden's `household_member_cap`, while for an `INDIVIDUAL` or `PATRON` plan the array must be empty. A roster that violates either rule is rejected with `ERR_HOUSEHOLD_CAP_EXCEEDED`; this same household check guards both membership creation and activation.

Activation moves a membership from `PENDING` to `ACTIVE`. Activation is permitted only when the membership is in `PENDING` status — otherwise `ERR_INVALID_STATE` — and only when the referenced plan's `active` flag is true; an inactive plan yields `ERR_PLAN_INACTIVE`. On activation the join fee is charged: because a brand-new annual term begins now, the member pays the full `annual_fee_cents` with no proration of any prior term, `paid_total_cents` is set to that charge, `term_start` is set to the current clock instant, and `term_end` is set to exactly 365 days after `term_start`. Guest passes are granted by tier at this moment: an `INDIVIDUAL` membership receives 0, a `HOUSEHOLD` membership receives the garden's `guest_pass_grant_household`, and a `PATRON` membership receives the garden's `guest_pass_grant_patron`; the granted number becomes `guest_passes_remaining`. The `renewal_count` stays at 0.

Renewal is the cyclic heart of the lifecycle: an `ACTIVE` membership renews back to `ACTIVE`, extending rather than restarting its term. Renewal is allowed only while the membership is `ACTIVE`, and only when the renewal window is open — that is, the current clock has reached or passed `term_end` minus 30 days — *or* when `auto_renew` is true (an auto-renewing membership may renew at any time). A renewal attempted before the 30-day window with `auto_renew` false is rejected with `ERR_RENEWAL_WINDOW_NOT_OPEN`. The charge on renewal credits the unused remainder of the current term against the new annual fee, and the order of evaluation is pinned. First, compute the unused days as the number of whole days remaining until the old `term_end`: take the time from the current clock to the old `term_end`, express it in days rounded up to a whole day, and floor the result at 0 so it is never negative. Second, take the daily value of the plan as `annual_fee_cents` divided by 365, keeping it as an exact (unrounded) real number. Third, multiply that daily value by the unused-days count and round the product half-up to whole cents — rounding exactly once, after the multiplication — to obtain the credit. Fourth, the renewal charge is the `annual_fee_cents` minus that credit, floored at 0 so it is never negative. That charge is added to `paid_total_cents`. The new `term_start` becomes the old `term_end` and the new `term_end` becomes the old `term_end` plus 365 days — an extension, not a reset to now. The guest-pass allotment is reset to the tier grant for the new term, and `renewal_count` increases by one. When a renewal happens exactly at expiry, with the current clock equal to `term_end`, the unused days are 0, the credit is 0, and the charge is the full annual fee.

Lapse and reinstatement complete the cycle. An `ACTIVE` membership whose `auto_renew` is false lapses to `LAPSED` when its term expires; the clock sweep performs this automatically, and a forced-lapse capability lets `GardenAdmin` or `GardenStaff` do it on demand. Either path runs the cascade described in Section 2.5 — cancelling future `HELD` reservations, withdrawing future `ENROLLED` registrations with the attendant waitlist promotions, and zeroing `guest_passes_remaining`. `LAPSED` is recoverable: a reinstatement returns a `LAPSED` membership to `ACTIVE`, but only if the plan is still `active` (otherwise `ERR_PLAN_INACTIVE`). Reinstatement is treated on the same fresh-term, full-fee basis as a first activation — the lapsed time is forfeited with no credit: the full `annual_fee_cents` is charged and added to `paid_total_cents`, `term_start` is set to now, `term_end` to 365 days after now, `guest_passes_remaining` is reset to the tier grant, and `renewal_count` increases by one. Finally, a membership in `PENDING`, `ACTIVE`, or `LAPSED` may be cancelled to the terminal `CANCELLED` state; cancellation cascades to cancel every `HELD` reservation owned by the membership — releasing each reservation's heads from its slot's `held_count` — and sets `guest_passes_remaining` to 0. A membership not in one of those three states cannot be cancelled and yields `ERR_INVALID_STATE`. Renew, cancel, reinstate, and forced-lapse all advance the membership's `version`.

### 3.3. Timed-Entry Reservations

A reservation holds gate capacity for a party at a particular slot. It is created by a `Visitor` or by `GardenStaff` and names the garden's `garden_id`, the slot's `time_slot_id`, and optionally a `membership_id` (empty string for a non-member, paid general-admission party). The party is described by three head counts: `member_heads`, the heads riding free under an included-admission membership; `guest_heads`, the heads covered by spending guest passes from that membership; and `paid_heads`, the heads paying general admission — members beyond their allotment, or non-members. Each defaults to 0. A `reciprocal` boolean, defaulting to false, marks the paid heads to be priced with the reciprocal-network discount instead of full general admission.

The party must be well formed. No head count may be negative, the party may not be entirely empty (the three counts may not all be zero), and `member_heads` or `guest_heads` may not be claimed without an attached membership; any of these defects yields `ERR_INVALID_HEAD_SPLIT`. The reservation's `party_size` is the sum `member_heads` plus `guest_heads` plus `paid_heads`, and it is this total that is held against the slot. Claiming member or guest heads engages the membership-active gate: the attached membership must be in `ACTIVE` status, failing which the create is rejected with `ERR_MEMBERSHIP_NOT_ACTIVE`. Guest heads additionally require sufficient allotment — `guest_heads` must not exceed the membership's `guest_passes_remaining` — or the create fails with `ERR_INSUFFICIENT_GUEST_PASSES`. When `reciprocal` is set, the garden must actually belong to a network (its `reciprocal_network_code` must be non-empty) and either there is no attached membership or the attached membership belongs to a *different* garden within that same network; otherwise the request is rejected with `ERR_RECIPROCAL_NOT_ELIGIBLE`. The optimistic-concurrency rule of Section 2.8 applies here through `expected_membership_version` whenever a membership is attached.

Admission is then priced and `admission_cents` is pinned at create time. Member heads and guest heads contribute nothing to the charge. The paid heads are priced per head, and the per-head rate is decided by the `reciprocal` flag: when `reciprocal` is true, the per-head rate is the slot's `ga_price_cents` multiplied by one minus the garden's `reciprocal_discount_pct`, rounded half-up to whole cents; when `reciprocal` is false, the per-head rate is simply `ga_price_cents`. The per-head rate is rounded *before* it is multiplied by `paid_heads`, and `admission_cents` is that rounded rate times `paid_heads`. Holding the party then requires room: the slot's current `held_count` plus this reservation's `party_size` must not exceed the slot's `capacity`, or the create fails with `ERR_SLOT_CAPACITY_EXCEEDED`. On success the slot's `held_count` increases by `party_size`, and if that brings `held_count` up to `capacity` the slot's `status` flips to `CLOSED`. When a membership is attached, the spent guest passes are deducted (`guest_passes_remaining` decreases by `guest_heads`) and the membership's `version` increments by one. The reservation opens in `HELD` status.

A `HELD` reservation has three possible fates, each with its own consequences. A `GardenStaff` member checks a reservation in at the gate, advancing `HELD` to `CHECKED_IN`; this is allowed only while the reservation is `HELD`, only when the current clock falls within the slot window (at or after `starts_at` and strictly before `ends_at`), and — if a membership is attached — only when that membership is `ACTIVE`, else `ERR_MEMBERSHIP_NOT_ACTIVE`. Check-in does *not* release capacity; the heads remain counted in `held_count`. Alternatively the visitor cancels a `HELD` reservation, advancing `HELD` to `CANCELLED`: this releases the reservation's `party_size` from the slot's `held_count`, reopens the slot to `OPEN` if it was `CLOSED` and now sits below capacity, and refunds the spent guest passes by adding `guest_heads` back to the membership's `guest_passes_remaining`. Finally, a reservation left `HELD` past its slot's `ends_at` is swept to `EXPIRED` by the next clock advance, which releases its `party_size` from `held_count` and reopens a `CLOSED` slot that now sits below capacity — but, unlike cancellation, an expiry does not refund guest passes. Only a `HELD` reservation may be cancelled or checked in; acting on a terminal reservation yields `ERR_INVALID_STATE`.

### 3.4. Special Exhibits and Event Tickets

Tickets to special exhibits are sold by a `Visitor` or by `GardenStaff`. A purchase names the garden's `garden_id`, the `exhibit_name`, the per-ticket list price `list_price_cents` (zero or positive), the `quantity` of tickets (at least 1), and optionally a `membership_id` (empty string for a non-member buyer). The total `charged_cents` is pinned at purchase, and the rounding order is critical. The member discount applies only when a membership is attached and that membership is in `ACTIVE` status; in that case the per-ticket price is the `list_price_cents` multiplied by one minus the plan's `event_discount_pct`, rounded half-up to whole cents, and the `charged_cents` is that rounded per-ticket price multiplied by `quantity`. When there is no membership or the membership is not `ACTIVE`, each ticket is charged at the full `list_price_cents` and `charged_cents` is `list_price_cents` times `quantity`. The discounted per-ticket price is rounded *before* multiplying by `quantity` — rounding per ticket then summing, never summing then rounding, because the two differ by cents. A purchased ticket opens in `PURCHASED` status.

A ticket may be refunded once. `GardenStaff` or `GardenAdmin` may refund a ticket, moving its `status` from `PURCHASED` to `REFUNDED`. A refund is permitted only on a ticket that is currently `PURCHASED`; attempting to refund a ticket in any other status — including a second refund of an already-`REFUNDED` ticket — is rejected with `ERR_REFUND_NOT_ALLOWED`.

### 3.5. Program Registration and Waitlist Promotion

Education programs and camps are filled through registrations. A `Visitor` or `GardenStaff` registers a participant against the garden's `garden_id`, the session's `program_session_id`, naming the `participant_name` and optionally a `membership_id` (empty string for a non-member registrant). Registration is refused outright with `ERR_SESSION_CLOSED` when the session's `status` is `CLOSED`. For an `OPEN` session, the outcome depends on room: if the session's `enrolled_count` is below its `capacity`, the registration enrolls immediately in `ENROLLED` status with `waitlist_rank` 0 and increments `enrolled_count`; if the session is full, the registration is *not* an error — it is placed `WAITLISTED` with a 1-based `waitlist_rank` equal to its position at the back of that session's waitlist.

Tuition is charged at the moment a registration becomes `ENROLLED`, whether that is at create time or later at promotion. The member program discount applies only when a membership is attached and that membership is `ACTIVE` at the instant tuition is charged: in that case `charged_cents` is the session's `tuition_cents` multiplied by one minus the plan's `program_discount_pct`, rounded half-up to whole cents; otherwise `charged_cents` is the full `tuition_cents`. A `WAITLISTED` registration is charged nothing — `charged_cents` is set only when its status becomes `ENROLLED`.

Withdrawal frees seats and bubbles the waitlist up. A `Visitor` or `GardenStaff` withdraws a registration to the terminal `WITHDRAWN` state. Withdrawing an `ENROLLED` registration decrements the session's `enrolled_count` and then promotes the head of that session's waitlist — the `WAITLISTED` registration whose `waitlist_rank` is 1 — to `ENROLLED`. Promotion is allowed when that registration is `WAITLISTED`, holds `waitlist_rank` 1 among its session's waitlisted registrations, and the session's `enrolled_count` is below `capacity` after the vacating withdrawal; on promotion the registration's status becomes `ENROLLED`, its `waitlist_rank` becomes 0, the session's `enrolled_count` increments, every remaining waitlisted registration of that session has its `waitlist_rank` reduced by one, and tuition is charged at that moment under the same member-discount rule. Withdrawing a registration that is itself `WAITLISTED` does not touch `enrolled_count`; it simply re-ranks the session's remaining waitlisted registrations below the withdrawn position, each dropping by one rank. Only an `ENROLLED` or `WAITLISTED` registration may be withdrawn; a terminal one yields `ERR_INVALID_STATE`. This same promotion chain is what fires when a lapse or cancellation cascade withdraws an enrolled registration.

### 3.6. Venue Rentals

Renting a venue is a two-step, request-then-confirm process with provisional and final pricing that can legitimately differ. A `Visitor` or `RentalCoordinator` requests a rental against the garden's `garden_id` and the venue's `venue_id`, supplying the inclusive window start `starts_at` and the exclusive window end `ends_at` (which must be strictly later than `starts_at`, else `ERR_INVALID_WINDOW`), and optionally a `membership_id`. The request lands in `REQUESTED` status with a provisional `quoted_cents` computed from the membership's tier and status as observed at request time. The price is built in a pinned order: first the billable hours are the rental's span (`ends_at` minus `starts_at`) expressed in hours and rounded *up* to a whole hour for any partial hour; second the subtotal is those hours multiplied by the venue's `hourly_rate_cents`; third eligibility for the member discount is evaluated against the subtotal — the discount applies only when a membership is attached and `ACTIVE`, its plan's `tier` is `PATRON`, and the subtotal is at least 50000 cents (five hundred dollars); fourth, when eligible, the discount is the subtotal multiplied by the venue's `member_rental_discount_pct`, rounded half-up to whole cents, and otherwise the discount is 0; fifth, the price is the subtotal minus the discount. At request time this price is stored as `quoted_cents`; `final_cents` remains 0 until confirmation.

A `RentalCoordinator` resolves a requested rental. Confirmation moves `REQUESTED` to `CONFIRMED`, but only after a venue-overlap check: there must be no existing `CONFIRMED` rental on the same venue whose window, widened by the venue's buffer on each side — from its `starts_at` minus the buffer to its `ends_at` plus the buffer — overlaps this rental's window. A collision is rejected with `ERR_VENUE_DOUBLE_BOOKED`. On a clean confirm the price is recomputed by the identical pinned formula but using the membership's tier and status as observed *now*, at confirm time, and stored as the locked `final_cents`; the original `quoted_cents` is preserved for audit. This is where provisional and final legitimately diverge: if a patron membership lapsed between request and confirm, the discount eligibility is lost at confirm and `final_cents` exceeds `quoted_cents`. A confirmed rental occupies the venue for overlap purposes. Alternatively the coordinator may reject a requested rental, moving `REQUESTED` to `REJECTED`, leaving `final_cents` at 0 and never occupying the venue. A rental in `REQUESTED` or `CONFIRMED` status may be cancelled — by the visitor or the coordinator — to the terminal `CANCELLED` state, which frees the venue for overlap purposes (a cancelled rental no longer occupies it). Confirming, rejecting, or cancelling a rental not in the required source state yields `ERR_INVALID_STATE`; only `REQUESTED` may be confirmed or rejected.

### 3.7. Donations, Deductibility, and the Conservancy Match

Gifts are recorded by a `Visitor`, a `DevelopmentOfficer`, or `GardenStaff`. A donation names the garden's `garden_id`, the `amount_cents` (at least 1), an optional `designation` — one of `GENERAL`, `CONSERVANCY`, or `CAPITAL`, defaulting to `GENERAL` — and an optional `membership_id` (empty string for an anonymous or non-member gift). The donation opens in `RECORDED` status, and its `tax_deductible_cents` is pinned at creation. Deductibility nets out the fair-market value of any benefit the donor received: a benefit is recognized only for a `GENERAL` gift of at least 25000 cents (a token-gift premium), in which case `tax_deductible_cents` is the `amount_cents` minus 2000 cents (the premium's fair-market value). For a `GENERAL` gift below that threshold, and for every `CONSERVANCY` or `CAPITAL` gift regardless of amount, the full `amount_cents` is deductible.

Each garden may hold at most one conservancy fund, created by a `DevelopmentOfficer` or `GardenAdmin` against the `garden_id` with an optional `match_ratio` (the multiplier applied to each conservancy gift while the campaign runs, defaulting to 0) and an optional `match_cap_cents` (the maximum total match the campaign will ever pay out, defaulting to 0). A second attempt to create a fund for a garden that already has one is rejected with `ERR_FUND_ALREADY_EXISTS`. The fund opens with its `campaign_status` at `OPEN`, `pledged_total_cents` at 0, and `matched_total_cents` at 0. When a donation designated `CONSERVANCY` is recorded, it accrues match as a side effect against the fund, in a pinned order: while the campaign is `OPEN`, compute the raw match as the donation's `amount_cents` multiplied by the fund's `match_ratio`, rounded half-up to whole cents; compute the remaining cap as the fund's `match_cap_cents` minus its current `matched_total_cents`, floored at 0; the applied match is the smaller of the raw match and the remaining cap. While the campaign is `CLOSED`, no match accrues and the applied match is 0. Regardless of match, the donation's `amount_cents` is added to the fund's `pledged_total_cents`, and the applied match is added to `matched_total_cents`. A `DevelopmentOfficer` closes the campaign, moving `campaign_status` from `OPEN` to `CLOSED`, after which conservancy gifts still pledge but accrue no further match; closing an already-`CLOSED` campaign yields `ERR_CAMPAIGN_CLOSED`.

Voiding a gift is a compensating reversal. A `DevelopmentOfficer` voids a `RECORDED` donation, moving its `status` to the terminal `VOIDED`; voiding an already-`VOIDED` donation yields `ERR_DONATION_VOIDED`. When the voided gift was designated `CONSERVANCY`, the reversal subtracts that donation's `amount_cents` from the fund's `pledged_total_cents` and subtracts the exact match this donation had contributed from the fund's `matched_total_cents`, conserving both running totals so that the fund reflects only its live, un-voided gifts.

## 4. Endpoint Definitions

All endpoints are mounted under the `/v1` prefix, except the administrative clock control. Creating a new resource returns HTTP 201 with the created resource in `data`; reads, lists, and state-changing actions on existing resources return HTTP 200 with the affected resource (or, for the clock, its sweep report). List endpoints accept the `limit` and `offset` query parameters of Section 2.3 in addition to the filters noted in their descriptions.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Advance the logical clock to a supplied ISO 8601 UTC instant; runs the reservation-expiry and membership-lapse sweeps | GardenAdmin |
| POST | `/v1/gardens` | Create a garden (tenant root) | GardenAdmin |
| GET | `/v1/gardens/{garden_id}` | Read a garden | GardenAdmin, GardenStaff, RentalCoordinator, DevelopmentOfficer, Visitor |
| POST | `/v1/membership-plans` | Create a membership plan for a tier | GardenAdmin |
| GET | `/v1/membership-plans/{plan_id}` | Read a membership plan | GardenAdmin, GardenStaff, RentalCoordinator, DevelopmentOfficer, Visitor |
| GET | `/v1/membership-plans` | List/filter plans by garden and/or tier | GardenAdmin, GardenStaff, RentalCoordinator, DevelopmentOfficer, Visitor |
| POST | `/v1/memberships` | Create a membership in PENDING status | Visitor, GardenStaff |
| GET | `/v1/memberships/{membership_id}` | Read a membership | GardenAdmin, GardenStaff, RentalCoordinator, DevelopmentOfficer, Visitor |
| GET | `/v1/memberships` | List/filter memberships by garden, plan, and/or status | GardenAdmin, GardenStaff, RentalCoordinator, DevelopmentOfficer, Visitor |
| POST | `/v1/memberships/{membership_id}/activate` | Activate a PENDING membership | Visitor, GardenStaff |
| POST | `/v1/memberships/{membership_id}/renew` | Renew an ACTIVE membership | Visitor, GardenStaff |
| POST | `/v1/memberships/{membership_id}/reinstate` | Reinstate a LAPSED membership | Visitor, GardenStaff |
| POST | `/v1/memberships/{membership_id}/lapse` | Force an ACTIVE membership to LAPSED | GardenAdmin, GardenStaff |
| POST | `/v1/memberships/{membership_id}/cancel` | Cancel a membership (terminal) | Visitor, GardenStaff |
| POST | `/v1/time-slots` | Create a timed-entry slot | GardenAdmin, GardenStaff |
| GET | `/v1/time-slots/{slot_id}` | Read a time slot | GardenAdmin, GardenStaff, RentalCoordinator, DevelopmentOfficer, Visitor |
| GET | `/v1/time-slots` | List/filter time slots by garden and/or status | GardenAdmin, GardenStaff, RentalCoordinator, DevelopmentOfficer, Visitor |
| POST | `/v1/reservations` | Create a timed-entry reservation (OCC on attached membership) | Visitor, GardenStaff |
| GET | `/v1/reservations/{reservation_id}` | Read a reservation | GardenAdmin, GardenStaff, RentalCoordinator, DevelopmentOfficer, Visitor |
| GET | `/v1/reservations` | List/filter reservations by garden, slot, membership, and/or status | GardenAdmin, GardenStaff, RentalCoordinator, DevelopmentOfficer, Visitor |
| POST | `/v1/reservations/{reservation_id}/check-in` | Check in a HELD reservation | GardenStaff |
| POST | `/v1/reservations/{reservation_id}/cancel` | Cancel a HELD reservation | Visitor, GardenStaff |
| POST | `/v1/event-tickets` | Purchase special-exhibit/event tickets | Visitor, GardenStaff |
| GET | `/v1/event-tickets/{ticket_id}` | Read an event ticket | GardenAdmin, GardenStaff, RentalCoordinator, DevelopmentOfficer, Visitor |
| GET | `/v1/event-tickets` | List/filter event tickets by garden, membership, and/or status | GardenAdmin, GardenStaff, RentalCoordinator, DevelopmentOfficer, Visitor |
| POST | `/v1/event-tickets/{ticket_id}/refund` | Refund a purchased event ticket | GardenStaff, GardenAdmin |
| POST | `/v1/program-sessions` | Create an education program/camp session | GardenAdmin, GardenStaff |
| GET | `/v1/program-sessions/{session_id}` | Read a program session | GardenAdmin, GardenStaff, RentalCoordinator, DevelopmentOfficer, Visitor |
| GET | `/v1/program-sessions` | List/filter program sessions by garden and/or status | GardenAdmin, GardenStaff, RentalCoordinator, DevelopmentOfficer, Visitor |
| POST | `/v1/program-sessions/{session_id}/close` | Close a session to new enrollments | GardenAdmin, GardenStaff |
| POST | `/v1/registrations` | Register a participant (ENROLLED if room, else WAITLISTED) | Visitor, GardenStaff |
| GET | `/v1/registrations/{registration_id}` | Read a registration | GardenAdmin, GardenStaff, RentalCoordinator, DevelopmentOfficer, Visitor |
| GET | `/v1/registrations` | List/filter registrations by garden, session, membership, and/or status | GardenAdmin, GardenStaff, RentalCoordinator, DevelopmentOfficer, Visitor |
| POST | `/v1/registrations/{registration_id}/withdraw` | Withdraw a registration (promotes head waitlister) | Visitor, GardenStaff |
| POST | `/v1/venues` | Create a rentable venue | GardenAdmin, RentalCoordinator |
| GET | `/v1/venues/{venue_id}` | Read a venue | GardenAdmin, GardenStaff, RentalCoordinator, DevelopmentOfficer, Visitor |
| GET | `/v1/venues` | List/filter venues by garden | GardenAdmin, GardenStaff, RentalCoordinator, DevelopmentOfficer, Visitor |
| POST | `/v1/rentals` | Request a venue rental (provisional quote) | Visitor, RentalCoordinator |
| GET | `/v1/rentals/{rental_id}` | Read a rental | GardenAdmin, GardenStaff, RentalCoordinator, DevelopmentOfficer, Visitor |
| GET | `/v1/rentals` | List/filter rentals by garden, venue, membership, and/or status | GardenAdmin, GardenStaff, RentalCoordinator, DevelopmentOfficer, Visitor |
| POST | `/v1/rentals/{rental_id}/confirm` | Confirm a requested rental (locks final price, overlap check) | RentalCoordinator |
| POST | `/v1/rentals/{rental_id}/reject` | Reject a requested rental | RentalCoordinator |
| POST | `/v1/rentals/{rental_id}/cancel` | Cancel a requested or confirmed rental | Visitor, RentalCoordinator |
| POST | `/v1/donations` | Record a donation/conservancy gift | Visitor, DevelopmentOfficer, GardenStaff |
| GET | `/v1/donations/{donation_id}` | Read a donation | GardenAdmin, GardenStaff, RentalCoordinator, DevelopmentOfficer, Visitor |
| GET | `/v1/donations` | List/filter donations by garden, membership, designation, and/or status | GardenAdmin, GardenStaff, RentalCoordinator, DevelopmentOfficer, Visitor |
| POST | `/v1/donations/{donation_id}/void` | Void a recorded donation | DevelopmentOfficer |
| POST | `/v1/conservancy-funds` | Create the garden's conservancy match fund (one per garden) | DevelopmentOfficer, GardenAdmin |
| GET | `/v1/conservancy-funds/{fund_id}` | Read the conservancy fund | GardenAdmin, GardenStaff, RentalCoordinator, DevelopmentOfficer, Visitor |
| GET | `/v1/conservancy-funds` | List/filter the conservancy fund(s) for a garden | GardenAdmin, GardenStaff, RentalCoordinator, DevelopmentOfficer, Visitor |
| POST | `/v1/conservancy-funds/{fund_id}/close-campaign` | Close the match campaign | DevelopmentOfficer |

The clock control accepts a single field, `to_iso8601`, the target instant; its response reports the resulting `now`, the `lapsed_membership_ids`, and the `expired_reservation_ids` produced by the sweeps.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VALIDATION | 422 |
| ERR_CROSS_GARDEN_REFERENCE | 422 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_MEMBERSHIP_VERSION | 412 |
| ERR_MEMBERSHIP_NOT_ACTIVE | 409 |
| ERR_INVALID_WINDOW | 422 |
| ERR_HOUSEHOLD_CAP_EXCEEDED | 422 |
| ERR_INSUFFICIENT_GUEST_PASSES | 409 |
| ERR_RECIPROCAL_NOT_ELIGIBLE | 422 |
| ERR_VENUE_DOUBLE_BOOKED | 409 |
| ERR_SLOT_CAPACITY_EXCEEDED | 409 |
| ERR_SESSION_CLOSED | 409 |
| ERR_PLAN_INACTIVE | 409 |
| ERR_RENEWAL_WINDOW_NOT_OPEN | 409 |
| ERR_DONATION_VOIDED | 409 |
| ERR_CAMPAIGN_CLOSED | 409 |
| ERR_FUND_ALREADY_EXISTS | 409 |
| ERR_INVALID_HEAD_SPLIT | 422 |
| ERR_REFUND_NOT_ALLOWED | 409 |

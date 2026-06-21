# Country Club Membership API — Product Requirements Document

## 1. Introduction

This document specifies the backend service that runs the membership, billing, and amenity operations of a private country club. The club admits members under one of three membership categories — golf, social, or corporate — each with its own initiation fee, recurring dues, and food-and-beverage spending obligation. Members carry a running charge account (the "chit" ledger) for everything they consume on the grounds, from dining to pro-shop purchases to guest fees, and every billing period the club rolls those charges, the dues, and any food-and-beverage shortfall into a statement that must be settled.

The service is also a reservation and capacity-management system. Members book tee times, courts, and dining tables against a finite set of resources; categories have hard capacity limits that push excess applicants onto a waitlist; and the board can periodically levy a capital assessment across the membership base to fund large projects. Because several actors — members acting on their own accounts, club managers running operations, and billing clerks reconciling the ledger — touch overlapping data, the system must keep the membership account state, the billing state, the charge balance, the reservation occupancy map, and the waitlist all mutually consistent under concurrent access. The rules that govern that consistency, the order in which money is computed, and the precise points at which one action cascades into another are the substance of this specification.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers. `X-User-Role` declares the caller's role and must be exactly one of `ClubManager`, `BillingClerk`, or `Member`. `X-User-ID` identifies the acting principal. If `X-User-Role` is absent or names a role the system does not recognize, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the caller's role is `Member`, the `X-User-ID` header is also mandatory, and a missing `X-User-ID` on a `Member` call is likewise an `ERR_UNAUTHENTICATED` (401). Once a caller is authenticated, the system checks whether the role is permitted to perform the requested operation; a role acting outside its permitted operations is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The three roles map to club personnel as follows. When `X-User-Role` is `ClubManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may accept and record it but never compares it to any entity's `id`. The same holds for `BillingClerk`: its `X-User-ID` is an opaque operator identifier with no entity backing. When `X-User-Role` is `Member`, by contrast, `X-User-ID` is the `id` of the acting `Membership`; ownership checks on any resource that references a membership compare the resource's membership foreign key to `X-User-ID`. Concretely, a `Member` may only act on a `Membership`, `Reservation`, `Chit`, or `GuestPass` they own — meaning the resource's `membership_id` or `sponsor_membership_id` equals `X-User-ID`. A member attempting to mutate someone else's resource is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

A `ClubManager` runs club configuration and operations: creating clubs, categories, and resources; driving the membership lifecycle (activation, suspension, reinstatement, resignation settlement); completing reservations; checking guests in; managing capital assessments and the waitlist; and closing billing periods. A `BillingClerk` owns the charge-account and statement mechanics: posting and voiding chits, opening statements, and reading everything. A `Member` acts only on their own memberships, reservations, guest passes, and payments. Opening statements for a period is shared between `ClubManager` and `BillingClerk`. All read (GET) operations are available to all three roles.

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

List endpoints accept two pagination parameters. `limit` controls how many records are returned and defaults to 10 when omitted; it must be at least 1 and at most 100, and an out-of-range numeric value is silently clamped into that range rather than rejected (a `limit` below 1 becomes 1 and one above 100 becomes 100). `offset` controls how many records to skip from the start and defaults to 0, with a minimum of 0; a negative `offset` is likewise clamped up to 0. A `limit` or `offset` that is present but not a parseable integer is rejected with `ERR_INVALID_REQUEST` (HTTP 400), and the clamped values are what the response `meta` reports. Results on every list endpoint are sorted by `created_at` in ascending order before pagination is applied. The `meta` block of a list response reports `limit`, `offset`, `total_count` (the total number of matching records before pagination), and `has_more` (true when records remain beyond the current page).

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource is assigned a server-minted `id` that is a UUID with no type prefix. Most resources also carry three audit fields: `created_at`, a creation timestamp in ISO 8601 UTC with three fractional digits; `updated_at`, refreshed to the current instant on every mutation; and `version`, an integer that starts at 1 and increments by exactly one on every mutation of that resource. Whenever the narrative below says an operation "bumps the version" or "refreshes `updated_at`" of an entity, it means precisely these audit fields advance for that entity.

One entity is an exception. The `AssessmentCharge` — the per-member line item produced when a capital assessment is levied — is an immutable record carrying only `id` and `created_at`; it has neither an `updated_at` nor a `version` field, because it is never mutated after creation. All other entities (`Club`, `MembershipCategory`, `Membership`, `Resource`, `Reservation`, `Chit`, `GuestPass`, `CapitalAssessment`, `WaitlistEntry`, `Statement`) carry the full `created_at` / `updated_at` / `version` set.

### 2.5. Monetary Precision and Rounding

All monetary amounts in this system are stored and computed as integer cents; there are no fractional-cent values anywhere in a stored field or a response. Sums of integer-cent values (chit totals, statement line items, charge balances) require no rounding because they are exact. Two calculations do involve division and therefore pin a rounding rule explicitly. The resignation refund applies a percentage to the refundable equity and takes the floor of that product — that is, it rounds toward zero, discarding any fractional cent. The capital-assessment allocation floors each member's individual share and then distributes any leftover cents one at a time, as described in §3; summing each share before flooring is forbidden. Wherever a floor is taken, it is taken on the per-item computation, never on a pre-aggregated total.

### 2.6. The Billing Period Clock

The club advances through monthly billing periods tracked by `billing_period_index`, an integer counter that starts at 0 when a club is created. A separate counter, `closed_through_period_index`, records the most recent period whose statements have been finalized and starts at -1, meaning nothing has been closed yet. The period only advances when a manager closes the current period; the closing operation finalizes that period's statements before incrementing `billing_period_index`, so the act of closing and the act of advancing are a single coordinated step described in §3.

Time-sensitive operations — completing a reservation once its window has elapsed, and expiring stale waitlist offers — depend on a server logical clock rather than wall-clock time. Before any clock value is set, the logical clock reads `2026-01-01T00:00:00Z`; it is never the real wall-clock. An administrative capability lets a manager set the logical clock to an explicit UTC instant for deterministic testing of completion and expiry behavior.

### 2.7. The Two-Axis Membership State Model

A membership's life is governed by two state axes that evolve independently of one another. The account axis, `account_status`, tracks the member's standing: `PENDING`, `ACTIVE`, `SUSPENDED`, `RESIGNED_PENDING`, or `RESIGNED`, where `RESIGNED` is terminal. The billing axis, `billing_status`, tracks the member's payment standing: `CURRENT`, `PAST_DUE`, or `DELINQUENT`. Unlike the membership, whose two axes are exposed as the separate `account_status` and `billing_status` fields, every other stateful entity in the system — reservations, chits, guest passes, capital assessments, waitlist entries, and statements — carries a single `status` field holding its lifecycle state. The two membership axes never share a transition — a member can be `ACTIVE` yet `PAST_DUE` at the same time, or `SUSPENDED` yet `CURRENT`. Account-axis transitions are driven by lifecycle actions (activate, suspend, reinstate, resign, settle), while billing-axis transitions are driven by statement finalization and payment. Every transition on either axis bumps `Membership.version`.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, each pinned to the current `version` of a parent resource so that a caller working from a stale view of capacity or occupancy cannot silently corrupt shared state.

Booking a reservation is guarded against the target `Resource`'s version. A reservation-create request must carry `expected_resource_version`, a non-optional field whose value is the `version` of the `Resource` the client last observed. A resource's `version` is bumped every time a reservation is confirmed, cancelled, or amended against it, because each of those changes the slot-occupancy map. If `expected_resource_version` does not match the resource's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412) before the overlap check runs — the stale version means the client is reasoning about an out-of-date picture of which slots are free, and the system refuses rather than risk a false "available" answer.

Accepting a waitlist offer is guarded against the target `MembershipCategory`'s version. An accept request must carry `expected_category_version`, a non-optional field whose value is the `version` of the `MembershipCategory` the client last observed when the offer was seen. A category's `version` is bumped on every activation, settlement, and count recompute that changes `active_member_count`. If `expected_category_version` does not match the category's current `version`, the accept is rejected with `ERR_STALE_VERSION` (HTTP 412) before a seat can be granted — the stale version means the client's view of remaining capacity is out of date, and the system refuses rather than risk over-allocating a seat. Endpoints other than these two booking and accept operations take no version field.

### 2.9. Cascades, Recomputes, and Compensating Reversals

Many operations in this domain mutate more than one entity. The general principles, detailed per-workflow in §3, are: a charge posted to a member always debits that member's `charge_balance_cents`; a charge voided always credits it back as a compensating reversal; freeing a category seat always re-evaluates the waitlist for a promotion; and any change to `active_member_count` re-derives that computed count rather than blindly adjusting it. The `charge_balance_cents` of a membership is never allowed to fall below zero. Computed fields — `charge_balance_cents`, `fb_spend_period_cents`, `active_member_count`, `guest_visits_used_period`, `refund_owed_cents`, and the statement breakdown fields — are derived from the underlying ledger and counters; the narrative below states, for each operation, exactly which of these are refreshed.

### 2.10. Nested Reads and Reference Validation

References supplied in a path or body are validated left to right against existence: the club, then the membership, resource, reservation, category, assessment, waitlist entry, guest pass, or statement named, in that reading order. Any referenced resource that does not exist yields `ERR_NOT_FOUND` (HTTP 404). List endpoints support filtering by the foreign keys their resources carry — for example listing reservations by `resource_id` or `membership_id`, listing chits by `membership_id` or `club_id`, listing memberships by `club_id`, `category_id`, or `primary_member_id`, and listing assessment charges by `membership_id` or `assessment_id` — so a caller can reach child records from a parent identifier.

### 2.11. Validation Ordering

When several checks could fire on the same request, they are evaluated in a fixed priority order so that the reported error is deterministic. Authentication comes first: the presence and validity of `X-User-Role`, then the presence of `X-User-ID` for `Member` calls, both surfacing `ERR_UNAUTHENTICATED`. Role authorization (`ERR_UNAUTHORIZED`) is checked next, followed by member ownership (`ERR_NOT_RESOURCE_OWNER`). Existence of every referenced resource (`ERR_NOT_FOUND`) is checked before any state or business rule. Only then is the target's state validated for the requested transition (`ERR_INVALID_STATE`). After state, optimistic-concurrency version matching (`ERR_STALE_VERSION`) is checked on the two guarded writes. The remaining business, safety, temporal, fiscal, and well-formedness checks follow, each described alongside the workflow it guards in §3. The practical consequence is that, for instance, a request naming a non-existent resource always reports `ERR_NOT_FOUND` rather than a downstream state or capacity error, and a transition attempted from the wrong state reports `ERR_INVALID_STATE` before any version or capacity check is consulted.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Club and Its Catalog

A `ClubManager` creates a club by supplying its `name` and, optionally, three policy knobs: `fb_minimum_carryover_allowed` (whether unspent food-and-beverage credit rolls forward, defaulting to false), `resignation_refund_pct` (the percentage of refundable equity returned at resignation, defaulting to 80), and `guest_visits_cap_per_period` (the per-period guest-visit ceiling for a single sponsor, defaulting to 4). When supplied, `resignation_refund_pct` must be an integer in the inclusive range 0 through 100 and `guest_visits_cap_per_period` must be a non-negative integer; a value outside those bounds is rejected with `ERR_INVALID_REQUEST` (HTTP 400). At creation the club's `billing_period_index` is initialized to 0 and its `closed_through_period_index` to -1.

Each club offers memberships through one or more categories. A manager creates a `MembershipCategory` by supplying the owning `club_id`, a `code` that must be one of `GOLF`, `SOCIAL`, or `CORPORATE` and must be unique among the categories of that same club, and the economic terms: `initiation_fee_cents` (the one-time fee charged at activation), `refundable_equity_cents` (the portion of that initiation treated as refundable equity, which must not exceed `initiation_fee_cents`), `monthly_dues_cents` (recurring monthly dues), `fb_minimum_cents` (the per-period food-and-beverage minimum spend this category must meet), `capacity` (the maximum number of memberships that may simultaneously hold a seat in this category), and `guest_fee_cents` (the flat fee charged to a sponsor for each guest visit hosted under this category). A category may optionally set `allows_golf`; when omitted it defaults to false, and a category whose `allows_golf` is false bars its members from booking tee-time resources. A category also exposes the computed `active_member_count`, initialized to 0 at creation, which counts the memberships in this category whose `account_status` is either `ACTIVE` or `SUSPENDED`. A create request whose `refundable_equity_cents` exceeds `initiation_fee_cents`, or that omits a required field, names an invalid enum, or supplies a non-positive amount where a positive integer is required, is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The six category economic amounts (`initiation_fee_cents`, `refundable_equity_cents`, `monthly_dues_cents`, `fb_minimum_cents`, `capacity`, and `guest_fee_cents`) are each validated as non-negative integers — zero is accepted, and only a negative value or a non-integer is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Reservable amenities are modeled as resources. A manager creates a `Resource` under a `club_id` with a `kind` of `TEE_TIME`, `COURT`, or `DINING_TABLE` and a human `label`. Two further inputs shape its booking behavior: `turnaround_minutes`, the mandatory buffer in minutes that must separate the end of one reservation from the start of the next on this resource (defaulting to 0 and applying to `TEE_TIME` and `COURT`), and `seat_capacity`, which for a `DINING_TABLE` is the maximum number of overlapping party seats (defaulting to 1). When supplied, `turnaround_minutes` must be a non-negative integer and `seat_capacity` must be an integer of at least 1; a value outside those bounds is rejected with `ERR_INVALID_REQUEST` (HTTP 400). For `TEE_TIME` and `COURT` resources, occupancy is exclusive — at most one reservation at a time — regardless of the `seat_capacity` value.

### 3.2. Admission: Memberships, Capacity, and the Waitlist

A prospective member begins as a record. A manager creates a `Membership` against a `club_id` and a `category_id`, supplying the `holder_name` and, for a corporate designated user, an optional `primary_member_id` that points at the roster head's membership; the head's own record and all non-corporate records leave `primary_member_id` null. A new membership starts with `account_status` of `PENDING` and `billing_status` of `CURRENT`.

Bringing a member into the club is the activate action, performed by a manager, which moves a membership from `PENDING` to `ACTIVE`. Activation is gated on capacity: it is permitted only when the category's `active_member_count` is strictly less than its `capacity`; if the category is already at or above capacity, the activation is refused with `ERR_CATEGORY_AT_CAPACITY` (HTTP 409) and the applicant must instead go through the waitlist. The membership must be in `PENDING` for activation to be valid; activating from any other account state yields `ERR_INVALID_STATE` (HTTP 409). On a successful activation the system records `activated_period_index` as the club's current `billing_period_index`; posts the initiation charge as a chit of kind `EVENT` whose `amount_cents` equals the category's `initiation_fee_cents` and which does not count toward the food-and-beverage minimum, debiting the member's `charge_balance_cents` by that amount; and recomputes the category's `active_member_count`, which now rises by one. The membership's `version` is bumped. While a membership is `PENDING`, `activated_period_index` is null.

When a category is full, applicants queue. A manager adds an applicant to a category's waitlist by creating a `WaitlistEntry` with the `club_id`, the desired `category_id`, and the `applicant_name`; it begins in `WAITING`. A seat becomes available to the queue in two ways. A manager may explicitly offer a waiting entry when the category has spare capacity — that is, when `active_member_count` is strictly below `capacity` — moving it from `WAITING` to `OFFERED`; offering an entry whose category is at capacity is refused with `ERR_CATEGORY_AT_CAPACITY` (409). Alternatively, an offer is generated automatically as a cascade when a seat is freed by a resignation settlement, as described in §3.3. In either case, transitioning to `OFFERED` records `offered_period_index` as the club's current `billing_period_index` and bumps the entry's `version`. An offer is a standing promise to the earliest-queued applicant; when the system must pick which waiting entry to promote, it promotes the one with the earliest `created_at`.

An offered applicant is brought in by the accept action. Accepting an `OFFERED` entry re-checks that the category still has a free seat — `active_member_count` strictly below `capacity`, since a seat may have been taken since the offer — and refuses with `ERR_CATEGORY_AT_CAPACITY` (409) if not. Accept is also one of the two operations guarded by optimistic concurrency: the request must carry `expected_category_version` matching the category's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (412) as described in §2.8. A successful accept moves the entry from `OFFERED` to `ACCEPTED` and cascades: it creates a fresh `Membership` in `PENDING` for the category and immediately activates it, applying the very same activation side effects — recording the activation period, posting the `EVENT` initiation chit, debiting the new member's `charge_balance_cents`, and recomputing `active_member_count`. The new membership's `id` is recorded on the entry as `created_membership_id`, the entry's `version` is bumped, and the category's `version` is bumped. An applicant may instead be turned away: a manager declines an `OFFERED` entry, moving it from `OFFERED` to `DECLINED`, and if any other entry for that category is still `WAITING`, the earliest by `created_at` is promoted to `OFFERED` as a cascade. Offers do not last indefinitely; their expiry is handled at period close, described in §3.7.

### 3.3. Leaving the Club: Resignation, Refund, and the Freed Seat

A member who wishes to leave initiates the resign action on their own membership, which a `Member` may perform only for the membership they own. Resignation is valid from either `ACTIVE` or `SUSPENDED`, and in both cases moves the account to `RESIGNED_PENDING`; resigning from any other state yields `ERR_INVALID_STATE` (409). Both branches are treated identically: each transitions to `RESIGNED_PENDING`, each computes the resignation refund, and each bumps `Membership.version`.

At resignation the system computes `refund_owed_cents`, the amount the club will owe the departing member once the resignation is settled. The gross refund is the category's `refundable_equity_cents` multiplied by the club's `resignation_refund_pct`, divided by 100, with the result floored to a whole cent (rounding toward zero). The amount actually owed then nets out any debt the member still carries: the refund owed is the gross refund minus the member's outstanding `charge_balance_cents` at resign time, floored at zero so it can never go negative. Two cases follow naturally from this single rule. When the member's `charge_balance_cents` is zero at resign time, no netting occurs and `refund_owed_cents` equals the gross refund exactly. When the member still owes money, the outstanding balance is subtracted from the gross refund — the club recovers the member's debt out of their equity refund — and if the debt exceeds the gross refund the owed amount bottoms out at zero. Until the refund is computed at resignation, `refund_owed_cents` is zero.

A resignation is finalized by a manager through the settle-resignation action, moving the account from `RESIGNED_PENDING` to the terminal `RESIGNED`. Settlement is permitted only when the member has fully cleared their charge account: the membership's `charge_balance_cents` must equal zero, every chit having been settled first. A settlement attempted with a non-zero balance is refused with `ERR_OUTSTANDING_BALANCE` (HTTP 409); settling from any state other than `RESIGNED_PENDING` yields `ERR_INVALID_STATE` (409). On settlement the freed seat is reclaimed: the category's `active_member_count` is recomputed and now falls by one, and that newly free seat cascades to the waitlist — if any `WaitlistEntry` for this category is in `WAITING`, the earliest by `created_at` is promoted to `OFFERED`. The membership's `version` is bumped.

A member's standing can also flex without leaving. A manager suspends an `ACTIVE` membership, moving it to `SUSPENDED`; a suspended member keeps their seat — they continue to count toward `active_member_count`, since suspended seats are held — but, as §3.4 details, may not book reservations. A manager reinstates a `SUSPENDED` membership back to `ACTIVE`. These two transitions form a cyclic loop on the account axis (`ACTIVE → SUSPENDED → ACTIVE`), and each bumps `Membership.version`. Suspending a membership that is not `ACTIVE`, or reinstating one that is not `SUSPENDED`, yields `ERR_INVALID_STATE` (409).

### 3.4. Booking Amenities: Reservations and the Amend Loop

A member books an amenity by creating a `Reservation` against a `club_id`, a `resource_id`, and their own `membership_id`, with a `starts_at` and an `ends_at` (both ISO 8601 UTC) and an optional `party_size` that defaults to 1. The reservation interval is half-open: it covers `starts_at` up to but not including `ends_at`. A member may only book under their own membership.

Several preconditions guard a booking, and the create carries the optimistic-concurrency field `expected_resource_version` that must match the resource's current `version`, failing with `ERR_STALE_VERSION` (412) per §2.8. The booking membership must be `ACTIVE`; a suspended or otherwise non-active member attempting to book is refused with `ERR_MEMBERSHIP_NOT_ACTIVE` (HTTP 409). If the resource is a tee time, the member's category must permit golf — `allows_golf` true — and a tee-time booking from a category whose `allows_golf` is false is refused with `ERR_GOLF_NOT_ALLOWED` (HTTP 422). The request must be semantically well-formed: `party_size` must be at least 1, and `ends_at` must be strictly after `starts_at`; a `party_size` below 1 or an `ends_at` at or before `starts_at` is refused with `ERR_VALIDATION` (HTTP 422).

The central booking rule is non-overlap on the resource. For a `TEE_TIME` or `COURT`, occupancy is exclusive: the requested interval, extended by the resource's `turnaround_minutes` buffer, must not overlap the interval of any existing `CONFIRMED` reservation on that resource — the buffer must separate the end of one booking from the start of the next, so a new booking is rejected if its window, padded by the turnaround on each side, touches another confirmed window. For a `DINING_TABLE`, multiple parties may overlap so long as the sum of the `party_size` values of all `CONFIRMED` reservations whose intervals overlap the requested interval does not exceed the resource's `seat_capacity`. A booking that violates either rule is refused with `ERR_RESOURCE_CONFLICT` (HTTP 409). A successful create places the reservation in `CONFIRMED`, holds the window on the resource, and bumps the resource's `version`.

Members revise bookings through a cyclic amend loop rather than by editing in place. A member proposes a new window for their own `CONFIRMED` reservation, moving it from `CONFIRMED` to `AMEND_PENDING`; the request supplies `proposed_starts_at` and `proposed_ends_at`, which are stored on the reservation while the original window continues to be held. The proposed window is checked for collision against other `CONFIRMED` reservations on the same resource using the same overlap/turnaround/seat-capacity logic, but the reservation's own current window is excluded from that check; the same golf-allowed and field-validity rules apply, surfacing `ERR_GOLF_NOT_ALLOWED` (422) or `ERR_VALIDATION` (422) as above, and a collision yields `ERR_RESOURCE_CONFLICT` (409). The member then resolves the pending amend one of two ways. Confirming the amend moves the reservation from `AMEND_PENDING` back to `CONFIRMED`, but only after the overlap is re-checked against the live occupancy map — a competing booking taken in the interim blocks the confirm with `ERR_RESOURCE_CONFLICT` (409); on success the proposed values become the new `starts_at` and `ends_at`, and `proposed_starts_at` and `proposed_ends_at` are cleared to null. Abandoning the amend also returns the reservation to `CONFIRMED` but discards the proposal, clearing `proposed_starts_at` and `proposed_ends_at` to null and retaining the original window. Each of propose, confirm, and abandon requires the reservation to be in the appropriate state (`CONFIRMED` for propose; `AMEND_PENDING` for confirm and abandon), failing otherwise with `ERR_INVALID_STATE` (409), and each bumps `Reservation.version`.

A member cancels their own `CONFIRMED` reservation, moving it to the terminal `CANCELLED` and freeing the held window on the resource. A manager completes a `CONFIRMED` reservation, moving it to the terminal `COMPLETED`, but only once the logical clock has reached or passed the reservation's `ends_at`; a completion attempted before that instant is rejected, as is a cancel or complete from any non-`CONFIRMED` state, with `ERR_INVALID_STATE` (409). Both cancel and complete bump `Reservation.version`. Because cancelling and amending change which slots are occupied, both — like a fresh booking — advance the resource's `version`, which is what the optimistic-concurrency guard on booking keys off.

### 3.5. The Charge Account: Chits, Guests, and Capital Assessments

The charge account is a per-member ledger of chits. A `BillingClerk` posts a chit by supplying the `club_id`, the charged `membership_id`, a positive `amount_cents`, and a `kind` of `DINING`, `PRO_SHOP`, `GUEST_FEE`, or `EVENT`. At post time the system pins `counts_toward_fb` to true exactly when the kind is `DINING` and false otherwise, stamps `period_index` with the club's current `billing_period_index`, debits the member's `charge_balance_cents` by `amount_cents`, and — when the chit is a `DINING` chit — refreshes the member's `fb_spend_period_cents`, which sums the `DINING` chit amounts posted in the current period for that membership. A new chit begins in `POSTED`. Posting bumps `Membership.version`. A chit's `amount_cents` must be positive.

A clerk voids a `POSTED` chit, moving it to the terminal `VOIDED`. Voiding is the compensating reversal of a post: it credits `amount_cents` back to the member's `charge_balance_cents`, and if the chit counted toward food-and-beverage spend, it recomputes the member's `fb_spend_period_cents` by removing that amount — so the balance and the food-and-beverage tally are exactly conserved across a post followed by a void. Voiding bumps `Membership.version`; a void attempted on a chit not in `POSTED` yields `ERR_INVALID_STATE` (409).

Guests visit under a member's sponsorship. A member registers a `GuestPass` for their own membership by supplying the `club_id`, the `sponsor_membership_id` (which must be the acting member's own), the `guest_name`, and the intended `visit_date` (which must be a parseable ISO 8601 instant, else the registration is refused with `ERR_VALIDATION`, 422); the pass begins in `REGISTERED`. A manager checks the guest in, moving the pass from `REGISTERED` to the terminal `CHECKED_IN`. Check-in is gated three ways: the pass must be `REGISTERED` (else `ERR_INVALID_STATE`, 409); the sponsoring membership must be `ACTIVE` (else `ERR_MEMBERSHIP_NOT_ACTIVE`, 409); and the sponsor must be under their guest-visit quota — the count of the sponsor's guest passes already `CHECKED_IN` in the club's current `billing_period_index`, surfaced as `guest_visits_used_period`, must be strictly less than the club's `guest_visits_cap_per_period`. The quota boundary is strict: when used visits equal the cap, the next check-in is refused with `ERR_GUEST_QUOTA_EXCEEDED` (HTTP 409). A successful check-in cascades a charge: it creates a chit of kind `GUEST_FEE` whose `amount_cents` is the sponsor category's `guest_fee_cents` and which does not count toward the food-and-beverage minimum, records that chit's `id` on the pass as `fee_chit_id`, debits the sponsor's `charge_balance_cents`, and recomputes the sponsor's `guest_visits_used_period`, which now rises by one. The pass's `version` is bumped. A member may instead cancel their own `REGISTERED` guest pass, moving it to the terminal `CANCELLED` and bumping its `version`; `fee_chit_id` stays null on a pass that is never checked in.

Periodically the board funds large projects through a capital assessment. A manager creates a `CapitalAssessment` against a `club_id` with a `description`, a `total_target_cents` that must be positive, and an `allocation_basis` of `EQUAL` or `DUES_WEIGHTED`; it begins in `DRAFT`. Levying the assessment moves it from `DRAFT` to the terminal `LEVIED` and fans the target amount out across the eligible membership base — the memberships whose `account_status` is `ACTIVE` or `SUSPENDED` at levy time. A levy is permitted only when at least one such eligible membership exists (and the target was positive at creation); a levy with no eligible members is refused with `ERR_NO_ELIGIBLE_MEMBERS` (HTTP 409). The allocation produces one `AssessmentCharge` per eligible membership, each carrying the owning `assessment_id`, the assessed `membership_id`, and that member's `amount_cents` share, and each share debits that member's `charge_balance_cents` as a cascade. After fan-out the assessment records `levied_amount_cents` as the sum of all the per-member shares it created and `levied_period_index` as the club's current `billing_period_index`, and its `version` is bumped. A manager may instead cancel a `DRAFT` assessment, moving it to the terminal `CANCELLED` and bumping its `version`. Levying or cancelling an assessment not in `DRAFT` yields `ERR_INVALID_STATE` (409).

The allocation arithmetic is pinned so that the per-member shares always sum exactly to `total_target_cents`. Under the `EQUAL` basis, the eligible memberships are taken in `created_at` ascending order; the base share is the target divided by the number of eligible memberships, floored to a whole cent; this base is assigned to every member; then the leftover — the target minus the base times the member count — is distributed one extra cent each to the first members in `created_at` ascending order, until the leftover is exhausted. Under the `DUES_WEIGHTED` basis, each eligible member's weight is their category's `monthly_dues_cents`; each member's raw share is the target multiplied by that member's weight and divided by the sum of weights over all eligible members; each member's base share is the floor of their raw share; the leftover — the target minus the sum of the floored bases — is distributed one extra cent each to the members with the largest fractional remainder in their raw share, ties broken by `created_at` ascending. In both bases the shares are floored individually first and the remainder is distributed afterward; computing a total and rounding once is forbidden.

### 3.6. Statements and the Charge-Account Payment Waterfall

Charges accumulate through a period and are reconciled into statements. A manager or clerk opens statements for the current period, which creates one `OPEN` `Statement` per eligible membership — those in `ACTIVE` or `SUSPENDED` — for the club's current `billing_period_index` if one is not already present; the operation is idempotent within a period, so calling it again does not duplicate statements. The open-statements call responds with HTTP 200 and an `array`-typed envelope whose `data` is every statement of the club for the current `billing_period_index` (both newly created and any already present), sorted by `created_at` ascending, with the pagination `meta` fields populated from that full set. Each `Statement` carries the `club_id`, the billed `membership_id`, and the `period_index` it covers, and its computed breakdown is filled in at finalization (described in §3.7): `dues_cents`, `fb_minimum_cents`, `fb_spend_cents`, `fb_shortfall_cents`, `chit_charges_cents`, `assessment_cents`, and `total_due_cents`. A statement begins in `OPEN`, becomes `FINALIZED` at period close, and reaches the terminal `PAID` once settled.

Members settle their charge account by making a payment against their own membership. The payment supplies a positive `amount_cents` that may not exceed the member's outstanding `charge_balance_cents`; a non-positive amount or one larger than the balance is refused with `ERR_PAYMENT_INVALID` (HTTP 422). The payment is applied to the member's `POSTED` chits oldest first, in `created_at` ascending order: each chit that the payment fully covers is settled, moving from `POSTED` to the terminal `SETTLED`, and the member's `charge_balance_cents` is reduced by the payment `amount_cents`. Any leftover from the payment that is not enough to fully cover the next oldest `POSTED` chit is not applied to settle that chit but is retained as a standing payment credit, so the chit stays `POSTED` while `charge_balance_cents` (derived as the sum of `POSTED` chit amounts minus that retained credit, floored at zero) still reflects the full reduction. As statements get covered by these settlements, any `FINALIZED` statement of this membership for whose `period_index` no `POSTED` chit remains moves from `FINALIZED` to `PAID`; this PAID transition touches only the statement (its dues, food-and-beverage shortfall, and assessment carry no separate ledger row, so the clearing of the period's chits is the sole gate) and does not itself settle additional chits or further reduce the charge balance. The payment then recomputes the member's `billing_status`: once no `FINALIZED` statement of the membership remains unpaid, the billing axis returns to `CURRENT` from either `PAST_DUE` or `DELINQUENT`. The payment bumps `Membership.version` (and the affected statements' versions). A member may pay only their own membership.

### 3.7. Closing the Period: Finalization, Carryover, and Aging

Closing a period is the club's monthly reconciliation, performed by a manager, and it is guarded by optimistic concurrency on the club itself — the request carries `expected_club_version`, which must match the club's current `version`. The guard is only enforced when `expected_club_version` is supplied (non-null): a present value that does not match the club's current `version` is rejected with `ERR_STALE_VERSION` (412), while an omitted or null `expected_club_version` skips the version check and the close proceeds. Closing performs a coordinated sequence: it finalizes every `OPEN` statement of the current period, advances the billing standing of members left owing money, expires stale waitlist offers, rolls food-and-beverage carryover where the club allows it, and then increments `billing_period_index` and records `closed_through_period_index`. The club's `version` is bumped.

Finalizing a statement moves it from `OPEN` to `FINALIZED` and computes its breakdown for a statement whose `period_index` is the period being closed. The dues line, `dues_cents`, is the category's `monthly_dues_cents`. The food-and-beverage figures come first because the total depends on them. The applicable minimum for the period, `fb_minimum_cents` on the statement, is the category's `fb_minimum_cents` net of any credit the member carried in: the effective minimum is the category minimum minus the member's `fb_credit_carried_cents`, floored at zero so it is never negative. The qualifying spend, `fb_spend_cents`, is the sum of the member's `DINING` chit amounts in the closing period whose status is `POSTED` or `SETTLED` (voided chits are excluded). The food-and-beverage shortfall billed this period, `fb_shortfall_cents`, is the effective minimum minus the qualifying spend, floored at zero so a member who meets or beats the minimum is billed no shortfall. The chit-charges line, `chit_charges_cents`, is the sum of all `POSTED` chit amounts of any kind in the closing period rolled into the statement. The assessment line, `assessment_cents`, is the sum of the `AssessmentCharge` amounts levied to this member in a period equal to the closing period. Finally, `total_due_cents` is the sum of the dues, the food-and-beverage shortfall, the chit charges, and the assessment, evaluated in that order with the shortfall computed first. Each finalized statement's `version` is bumped.

Whether unspent food-and-beverage credit rolls forward depends on the club's `fb_minimum_carryover_allowed` policy, and the two variants produce different shortfalls and different next-period minimums from identical chit data. When carryover is not allowed, `fb_credit_carried_cents` is always zero, so the effective minimum equals the category minimum outright, any surplus over the minimum is simply discarded, and the shortfall is the category minimum minus the period's qualifying spend, floored at zero. When carryover is allowed, the effective minimum for the current period is reduced by whatever `fb_credit_carried_cents` the member brought in, and at finalization any surplus — the qualifying spend over the effective minimum, floored at zero — is written, capped at one period's `fb_minimum_cents`, into the member's `fb_credit_carried_cents` for the next period. A member who overspends the minimum thus banks credit (up to one minimum's worth) that lowers next period's effective minimum.

After a statement is finalized, the member's billing standing ages if money remains owed. A `FINALIZED` statement left with `total_due_cents` greater than zero and not yet `PAID` advances the member's billing axis from `CURRENT` to `PAST_DUE`. If a member is already `PAST_DUE` and a later period's close again leaves a `FINALIZED` unpaid statement, the billing axis advances from `PAST_DUE` to `DELINQUENT` — a second consecutive period of non-payment. These billing-axis advances are independent of the account axis and each bumps `Membership.version`; payment, as in §3.6, is the only thing that walks the billing axis back toward `CURRENT`.

Period close also ages the waitlist. Any `WaitlistEntry` still in `OFFERED` whose `offered_period_index` is earlier than the club's `billing_period_index` after the advance has let its offer lapse and is moved to the terminal `EXPIRED`; as with a decline, if another entry for that category is still `WAITING`, the earliest by `created_at` is promoted to `OFFERED` as a cascade. Each expiry bumps the entry's `version`.

### 3.8. The Test-Driving Clock

For deterministic testing of time-sensitive behavior, a manager may invoke an administrative capability that sets the server logical clock to an explicit UTC instant supplied as `to_iso8601` (a required field that must be a parseable ISO 8601 instant, else the call is refused with `ERR_INVALID_REQUEST`, 400); the call responds with HTTP 200 and an empty `data` object. This is the clock that reservation completion checks against `ends_at` and that period close compares against waitlist offer periods. Before it is ever set, the clock reads `2026-01-01T00:00:00Z`, and it is never tied to real wall-clock time.

## 4. Endpoint Definitions

All endpoints return their result in the standard envelope of §2.2. Endpoints that create a brand-new resource respond with HTTP 201; endpoints that modify an existing resource, drive a state transition, or read data respond with HTTP 200. Request bodies, side effects, and preconditions are not repeated here — they are specified in the §3 workflow narratives; this table is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/clubs` | Create a club with its billing and policy configuration | ClubManager |
| GET | `/clubs/{id}` | Fetch a club | ClubManager, BillingClerk, Member |
| POST | `/clubs/{id}/close-period` | Close the current period: finalize statements, age billing, expire offers, roll carryover, advance the period | ClubManager |
| POST | `/clubs/{id}/open-statements` | Open OPEN statements for the current period for eligible memberships (idempotent) | ClubManager, BillingClerk |
| POST | `/membership-categories` | Create a membership category with its economic terms | ClubManager |
| GET | `/membership-categories/{id}` | Fetch a category including computed active member count | ClubManager, BillingClerk, Member |
| GET | `/membership-categories` | List categories, filterable by club | ClubManager, BillingClerk, Member |
| POST | `/memberships` | Create a PENDING membership for a category | ClubManager |
| GET | `/memberships/{id}` | Fetch a membership with computed balances and counters | ClubManager, BillingClerk, Member |
| GET | `/memberships` | List memberships, filterable by club, category, or primary member | ClubManager, BillingClerk, Member |
| POST | `/memberships/{id}/activate` | Activate a PENDING membership (capacity-gated) | ClubManager |
| POST | `/memberships/{id}/suspend` | Suspend an ACTIVE membership | ClubManager |
| POST | `/memberships/{id}/reinstate` | Reinstate a SUSPENDED membership | ClubManager |
| POST | `/memberships/{id}/resign` | Resign own ACTIVE/SUSPENDED membership and compute the refund | Member |
| POST | `/memberships/{id}/settle-resignation` | Finalize a resignation (zero balance required); free the seat | ClubManager |
| POST | `/memberships/{id}/payments` | Pay toward own charge balance, settling chits oldest-first | Member |
| POST | `/resources` | Create a reservable resource | ClubManager |
| GET | `/resources/{id}` | Fetch a resource | ClubManager, BillingClerk, Member |
| GET | `/resources` | List resources, filterable by club | ClubManager, BillingClerk, Member |
| POST | `/reservations` | Book a resource window (OCC-guarded on resource version) | Member |
| GET | `/reservations/{id}` | Fetch a reservation | ClubManager, BillingClerk, Member |
| GET | `/reservations` | List reservations, filterable by resource, membership, or club | ClubManager, BillingClerk, Member |
| POST | `/reservations/{id}/propose-amend` | Propose a new window for own CONFIRMED reservation | Member |
| POST | `/reservations/{id}/confirm-amend` | Confirm the proposed window (re-checks overlap) | Member |
| POST | `/reservations/{id}/abandon-amend` | Abandon a pending amend, keeping the original window | Member |
| POST | `/reservations/{id}/cancel` | Cancel own CONFIRMED reservation and free the window | Member |
| POST | `/reservations/{id}/complete` | Mark a CONFIRMED reservation COMPLETED (clock at/after end) | ClubManager |
| POST | `/chits` | Post a chit to a membership's charge account | BillingClerk |
| GET | `/chits/{id}` | Fetch a chit | ClubManager, BillingClerk, Member |
| GET | `/chits` | List chits, filterable by membership or club | ClubManager, BillingClerk, Member |
| POST | `/chits/{id}/void` | Void a POSTED chit (compensating reversal) | BillingClerk |
| POST | `/guest-passes` | Register a sponsored guest pass | Member |
| GET | `/guest-passes/{id}` | Fetch a guest pass | ClubManager, BillingClerk, Member |
| GET | `/guest-passes` | List guest passes, filterable by sponsor, club, or fee chit | ClubManager, BillingClerk, Member |
| POST | `/guest-passes/{id}/check-in` | Check a guest in (quota-gated); post the guest fee | ClubManager |
| POST | `/guest-passes/{id}/cancel` | Cancel a REGISTERED guest pass | Member |
| POST | `/capital-assessments` | Create a DRAFT capital assessment | ClubManager |
| GET | `/capital-assessments/{id}` | Fetch a capital assessment | ClubManager, BillingClerk, Member |
| GET | `/capital-assessments` | List capital assessments, filterable by club | ClubManager, BillingClerk, Member |
| POST | `/capital-assessments/{id}/levy` | Levy a DRAFT assessment; fan out per-member charges | ClubManager |
| POST | `/capital-assessments/{id}/cancel` | Cancel a DRAFT assessment | ClubManager |
| GET | `/capital-assessments/{id}/charges` | List the assessment charges created by a levy | ClubManager, BillingClerk, Member |
| GET | `/assessment-charges/{id}` | Fetch a single assessment charge | ClubManager, BillingClerk, Member |
| GET | `/assessment-charges` | List assessment charges, filterable by membership or assessment | ClubManager, BillingClerk, Member |
| POST | `/waitlist-entries` | Add an applicant to a category's waitlist | ClubManager |
| GET | `/waitlist-entries/{id}` | Fetch a waitlist entry | ClubManager, BillingClerk, Member |
| GET | `/waitlist-entries` | List waitlist entries, filterable by category, club, or created membership | ClubManager, BillingClerk, Member |
| POST | `/waitlist-entries/{id}/offer` | Offer a WAITING entry when capacity is free | ClubManager |
| POST | `/waitlist-entries/{id}/accept` | Accept an OFFERED entry (OCC on category); create and activate a membership | ClubManager |
| POST | `/waitlist-entries/{id}/decline` | Decline an OFFERED entry; promote the next waiting entry | ClubManager |
| GET | `/statements/{id}` | Fetch a statement with its computed breakdown | ClubManager, BillingClerk, Member |
| GET | `/statements` | List statements, filterable by membership, club, or period | ClubManager, BillingClerk, Member |
| POST | `/_clock/set_current_utc` | Set the server logical clock to an explicit UTC instant | ClubManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_GOLF_NOT_ALLOWED` | 422 |
| `ERR_MEMBERSHIP_NOT_ACTIVE` | 409 |
| `ERR_RESOURCE_CONFLICT` | 409 |
| `ERR_CATEGORY_AT_CAPACITY` | 409 |
| `ERR_GUEST_QUOTA_EXCEEDED` | 409 |
| `ERR_OUTSTANDING_BALANCE` | 409 |
| `ERR_NO_ELIGIBLE_MEMBERS` | 409 |
| `ERR_PAYMENT_INVALID` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_VALIDATION` | 422 |
</content>
</invoke>

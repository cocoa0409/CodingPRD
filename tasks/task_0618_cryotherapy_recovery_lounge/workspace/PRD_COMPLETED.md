# Cryotherapy & Recovery Lounge API — Product Requirements Document

## 1. Introduction

The Cryotherapy & Recovery Lounge platform powers a chain of recovery studios in the mold of the modern hyper-wellness lounge. Each lounge offers a menu of recovery services — whole-body cryotherapy, red-light therapy, compression, and infrared sauna — delivered in dedicated rooms and equipment bays, supervised by on-shift technicians, and paid for through a blend of recurring memberships and prepaid credit packs. This document specifies the REST API that runs the entire operation: the service catalogue, room and technician scheduling across multiple locations, membership billing with freeze and upgrade mechanics, prepaid credit packs with an introductory offer, medical waiver and contraindication screening, and the booking lifecycle that ties all of these together.

The system must reconcile two distinct kinds of difficulty. The first is **temporal correctness**: rooms are a finite resource booked into half-open time intervals that include a turnover buffer, technicians must be physically on a covering shift, and recurring billing advances on fixed thirty-day cycles. The second is **wallet correctness**: every booking draws service credits from a member's subscription grant and prepaid packs in a precise waterfall, every cancellation refunds them to their original source, and every monetary figure — signup fees, proration, refunds, late-cancel penalties — is computed in integer cents with a single, pinned rounding step. Because the platform is multi-location and several actors may act on the same member or room, the API also exposes a deterministic logical clock and an idempotent billing driver so that time-dependent behaviour can be tested precisely, and it guards its highest-contention writes with optimistic concurrency control.

This PRD is written for the engineers who will implement that API. It describes the domain first and the mechanics second; the precise contract for response envelopes, pagination, identifiers, and concurrency lives in Section 2, the business workflows in Section 3, and the consolidated endpoint and error tables in Sections 4 and 5.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. The API is mounted at the root path; all paths in this document are absolute from that root.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting principal and `X-User-Role` declares the operational capacity in which they are acting. If either header is missing, or if `X-User-Role` is not one of the recognized role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly four roles, spelled precisely as follows: `PlatformAdmin`, `LocationManager`, `Member`, and `Technician`.

When the acting role is permitted to reach an endpoint but is not allowed to act on the specific target resource, the request is rejected with `ERR_FORBIDDEN` (HTTP 403). The relationship between `X-User-ID` and resource ownership depends on the role's identity model:

- When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` (its waivers, subscription, credit packs, and bookings) compare that resource's member foreign key to `X-User-ID`. A `Member` may act only on their own resources.
- When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting `Technician`; ownership checks on any resource that references a `Technician` (for example, completing or no-showing a session) compare the acting technician against `X-User-ID`, and a technician may only dispose of a session while standing on one of their own covering shifts. The covering-shift ownership check is enforced only on the **completion** transition; marking a no-show does not require the acting technician to be on a covering shift (any `Technician` whose role reaches the endpoint may no-show a `BOOKED` session, subject only to the no-show transition's own state and clock gates in Section 3.5).
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`.
- When `X-User-Role` is `LocationManager`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`. A `LocationManager` acts as an operational proxy and may perform member-facing operations (booking, subscription management, waiver signing, pack purchase) on behalf of any member without being that member.

`PlatformAdmin` operates the platform itself: creating locations, the service menu, and membership plans, driving the logical clock, and advancing recurring billing. `LocationManager` runs an individual lounge: rooms, technicians, shifts, member onboarding, waiver revocation, and pack refunds, and may proxy member-booking and subscription actions. `Member` is the end customer who acts only on their own waivers, subscription, packs, and bookings. `Technician` is front-line staff who complete or no-show sessions while on a covering shift.

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

Every endpoint that returns a list of resources is paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, may not be smaller than 1, and may not exceed 100. The `offset` parameter is the number of items to skip from the start of the result set; when omitted it defaults to 0 and may not be negative. A `limit` outside the inclusive range of 1 to 100, or a negative `offset`, is rejected with `ERR_VALIDATION_PAGINATION` (HTTP 400).

Unless a specific endpoint states otherwise, list endpoints return resources sorted by their creation timestamp in ascending order. Every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the count of all matching resources before pagination and `has_more` indicates whether more results exist beyond the current page.

### 2.4. Common Resource Properties and the Logical Clock

Most resources in this system carry a standard set of system-managed fields. Each such resource exposes an `id` — a server-minted UUID with no type prefix that serves as identity only — along with a `created_at` timestamp recording when it was first created, an `updated_at` timestamp recording when it was last modified, and an integer `version` that begins at its initial value of `1` on creation and increments by one on every mutation. Timestamps are ISO 8601 UTC strings with three fractional digits.

Two entities are deliberately leaner. The `Invoice` resource is append-only and immutable after issue: it carries only `id` and `created_at`, and has neither an `updated_at` nor a `version` field. Every other entity — `Location`, `ServiceType`, `Room`, `Technician`, `TechnicianShift`, `MembershipPlan`, `Member`, `Waiver`, `Subscription`, `CreditPack`, and `Booking` — carries the full set of common fields.

All time-dependent behaviour reads from a **logical clock** rather than wall-clock time. At server startup the clock reads exactly `2026-01-01T00:00:00Z`, and until it is explicitly set it never falls back to real time. An administrative test-driving capability sets the clock to an arbitrary UTC instant supplied as `to_iso8601`, returning the new `current_utc`. All timestamps the server stamps — `signed_at` on a waiver, `cycle_anchor_at` on a subscription, `expires_at` on a credit pack, `created_at` on an invoice, and so on — are taken from this clock.

### 2.5. Monetary and Credit Precision

All money in this system is expressed and stored as **integer cents**; there are no fractional cents and no floating-point currency anywhere in the contract. Wherever a calculation requires rounding, the method is **round half up**, and each calculation in Section 3 names the single, pinned step at which that rounding occurs. Service credits are likewise whole integers: credit balances, grants, pack contents, and per-service costs are never fractional and are never rounded, because no credit operation ever produces a fraction.

Two invariants protect derived quantities from drifting below zero. A member's `credit_balance`, a subscription's `granted_credits_remaining`, and a credit pack's `remaining_credits` are each clamped so they can never be negative.

### 2.6. Derived-Field Reconciliation

Several fields are computed from other state rather than written directly, and the server keeps them reconciled immediately as their inputs change. A `Location` exposes `open_booking_count`, the number of that location's bookings whose status is `BOOKED`; it is initialized to zero at creation, incremented when a booking is created there, and decremented whenever a booking at that location leaves `BOOKED` (on completion, no-show, or cancellation). A `Subscription` exposes `current_cycle_end_at` — its `cycle_anchor_at` plus thirty days, treated as the exclusive end of the current cycle and the next bill date while `ACTIVE` — and `lifetime_paid_cents`, the sum of `amount_cents` across that subscription's invoices whose status is `PAID`. A `Member` exposes `credit_balance`, reconciled per the balance rule in Section 3 whenever any contributing subscription grant or pack changes.

Whenever the server recomputes a derived field on a resource, that recomputation is a mutation of the owning resource: it refreshes the resource's `updated_at` and increments its `version`. A reconciliation may be triggered indirectly — for example, debiting a credit pack during a booking recomputes the owning member's `credit_balance` even though the client addressed the booking, not the member.

### 2.7. Nested Resource Retrieval and Reference Integrity

When an endpoint path contains more than one resource identifier (for example, a waiver addressed beneath its member, or a credit pack addressed beneath its member), the server validates each identifier in left-to-right order and rejects the request with `ERR_NOT_FOUND` (HTTP 404) on the first identifier in the path that does not resolve to an existing resource. The identifiers validated this way include `location_id`, `member_id`, `room_id`, `booking_id`, `subscription_id`, `pack_id`, `waiver_id`, `technician_id`, `shift_id`, `service_type_id`, `plan_id`, and `invoice_id` wherever they appear as path parameters.

Separately, when a request body carries a foreign-key reference — such as `plan_id`, `room_id`, `service_type_id`, `home_location_id`, or `location_id` — and that reference does not resolve to an existing resource, the request is rejected with `ERR_REFERENCE_NOT_FOUND` (HTTP 404). Path-existence (`ERR_NOT_FOUND`) is distinct from body-reference existence (`ERR_REFERENCE_NOT_FOUND`); both carry 404 but signal different failures.

### 2.8. Validation Ordering

Across every endpoint, validations are evaluated in a fixed priority order so that the same request always fails for the same, earliest reason. The order is: (1) authentication of the headers, yielding `ERR_UNAUTHENTICATED`; (2) authorization of the role and ownership, yielding `ERR_FORBIDDEN`; (3) existence of every path-referenced resource, left to right, yielding `ERR_NOT_FOUND`; (4) existence of every foreign-key reference carried in the body of a POST that carries such references, yielding `ERR_REFERENCE_NOT_FOUND`; (5) pagination bounds on list endpoints, yielding `ERR_VALIDATION_PAGINATION`; (6) general body well-formedness — required fields present, enum values legal, integers within their declared ranges — yielding `ERR_INVALID_REQUEST`; (7) the freeze-cycles range check on a freeze request, yielding `ERR_FREEZE_CYCLES_INVALID`; (8) the optimistic-concurrency version check on guarded writes, yielding `ERR_STALE_VERSION`; (9) the state-validity check that the target resource is in a legal state for the requested transition, yielding `ERR_INVALID_STATE`; and (10) the location-open check, yielding `ERR_LOCATION_CLOSED`. The remaining business rules — duplicate subscription, inactive service, contraindication block, missing waiver, room overlap, shift overlap, staffing coverage, intro-offer uniqueness, upgrade direction, and credit sufficiency — are evaluated after these foundational checks; their relative ordering within the booking workflow is described in Section 3.5. This ordering is what guarantees, for instance, that a request against a missing resource fails as `ERR_NOT_FOUND` rather than being masked by a later state or business check.

### 2.9. Optimistic Concurrency Control

Two write operations are guarded against acting on stale data, and only these two carry a version field; every other endpoint omits it entirely.

The first guarded write is **booking creation**. A request to create a booking must carry `expected_room_version` holding the client's last observed `version` of the target `Room`. Because a successful booking create increments the room's `version` (the room's occupied intervals are part of its booking surface), a second create that still carries the previously observed room version is stale and is rejected with `ERR_STALE_VERSION` (HTTP 412). This is the sanctioned way to serialize two legitimately overlapping booking attempts on the same room without depending on request timing.

The second guarded write is the **subscription upgrade**. A request to upgrade a subscription must carry `expected_subscription_version` holding the client's last observed `version` of the target `Subscription`. A renewal at billing, a freeze, an unfreeze, or a prior upgrade all bump the subscription's `version` and re-anchor the cycle that proration depends on; an upgrade carrying a stale subscription version would prorate against an outdated cycle anchor and is therefore rejected with `ERR_STALE_VERSION` (HTTP 412). In both cases the rejection is purely a stale-version rejection: when the supplied expected version does not equal the parent's current `version`, the write is refused.

## 3. Business Logic & Workflows

### 3.1. Platform Configuration: Locations, Services, Rooms, and Technicians

A `PlatformAdmin` lays down the platform's foundations. Creating a location takes a `name`, a US `state_code` such as CA or TX, and an IANA `timezone` label; the location is born with `status` of `OPEN` and an `open_booking_count` of zero. The `timezone` is informational only — all clock logic is UTC. A location may later be moved between `OPEN` and `CLOSED`: closing a location is permitted only while it is `OPEN`, and re-opening is permitted only while it is `CLOSED`. While a location is `CLOSED`, two operations are refused with `ERR_LOCATION_CLOSED` (HTTP 409): creating a room at that location, and creating a booking there. Both closing and re-opening may be performed by a `PlatformAdmin` or a `LocationManager`.

The service menu is a flat catalogue of `ServiceType` entries created by a `PlatformAdmin`. Each service has a `code` — one of `WHOLE_BODY_CRYO`, `RED_LIGHT`, `COMPRESSION`, or `INFRARED_SAUNA`, unique across the menu (a create that reuses an existing menu `code` is rejected with `ERR_INVALID_REQUEST`, HTTP 400) — together with a display `name`, a `duration_minutes` of at least 5, a `buffer_minutes` of at least 0 representing the cleaning and turnover time added after a session before the room frees, and a `credit_cost` of at least 1 representing how many service credits one session of this service consumes. Two boolean toggles round out the entry: `requires_medical_clearance`, which when true means a contraindication flag blocks booking the service entirely (defaulting to false), and `active`, which when false hides the service from the menu and prevents it from being booked (defaulting to true).

Rooms and equipment bays are created beneath a specific location and tied to exactly one service. Creating a room takes a `service_type_id` identifying the single service this room delivers and a `name` such as "Cryo Chamber 1"; the room's `location_id` is taken from the path, and it is created with `status` of `AVAILABLE` (the only room status in this version). Each `Room` carries the foreign keys `location_id` and `service_type_id`. Rooms are listed through a flat collection filterable by `location_id`, `service_type_id`, and `status`.

Technicians are registered beneath a location as well. Registration takes a `full_name`; the technician's home `location_id` is taken from the path and the record is created with `status` of `ACTIVE` (the only technician status in this version). A `Technician`'s `id` equals `X-User-ID` when that technician acts. Technicians are listed through a flat collection filterable by `location_id` and `status`.

### 3.2. The Technician Schedule

Each technician keeps a schedule of shifts. A shift is created beneath a technician and takes a `location_id` (the location the technician is rostered at for this shift, which need not be their home location), a `starts_at` interpreted as the inclusive start bound, and an `ends_at` interpreted as the exclusive end bound, both ISO 8601 UTC; `ends_at` must be strictly after `starts_at`, and a request whose `ends_at` is less than or equal to its `starts_at` is rejected as malformed with `ERR_INVALID_REQUEST` (HTTP 400). The shift's `technician_id` is taken from the path, and it is created with `status` of `SCHEDULED`. A shift may later be cancelled by a `PlatformAdmin` or `LocationManager`, moving it from `SCHEDULED` to `CANCELLED`.

When a new shift is added, the server treats it as the half-open interval running from `starts_at` up to but not including `ends_at`, and refuses it if that interval intersects any existing `SCHEDULED` shift of the same technician. Two shifts that merely touch at an endpoint — one ending exactly when the next begins — do not overlap and are both permitted; only a genuine interior intersection is a conflict. A conflicting shift is rejected with `ERR_SHIFT_OVERLAP` (HTTP 409). Shifts are listed through a flat collection filterable by `technician_id`, `location_id`, and `status`. Shift creation and cancellation are operational setup performed by a `PlatformAdmin` or `LocationManager`.

### 3.3. Members, Waivers, and the Contraindication Gate

A member is registered by a `PlatformAdmin` or `LocationManager` with a `home_location_id` naming their default location, a unique `email` (a registration whose `email` matches an existing member's is rejected with `ERR_INVALID_REQUEST`, HTTP 400), a `full_name`, and a residence `state_code`. A new member is `ACTIVE` with `contraindication_flag` false, `intro_offer_used` false, and `credit_balance` zero. The `contraindication_flag` records whether the member's active screening reported a disqualifying contraindication, and `intro_offer_used` records whether the member has already taken the one-time intro pack; both are system-managed. A member's `id` equals `X-User-ID` when that member acts. Reading a member returns the live computed `credit_balance`.

Before a member can book anything, they must sign a **waiver** and complete contraindication screening. Signing a waiver — performed by the `Member` themselves or by a `LocationManager` on their behalf — takes a `screening_answers` map of contraindication question codes to boolean answers and a `has_contraindication` flag attesting whether a disqualifying condition was reported. The new waiver is stamped with a `signed_at` taken from the logical clock and is created `ACTIVE`; its `member_id` is taken from the path. A member has at most one `ACTIVE` waiver at a time: when a member already has an `ACTIVE` waiver and signs a fresh one, the prior `ACTIVE` waiver transitions to `SUPERSEDED` in the same request and the new waiver becomes the member's single `ACTIVE` waiver. On signing, the member's `contraindication_flag` is recomputed directly from the new active waiver's `has_contraindication`.

A `LocationManager` may **revoke** a member's `ACTIVE` waiver. Revocation is permitted only on the member's `ACTIVE` waiver; it moves that waiver from `ACTIVE` to `REVOKED` and sets the member's `contraindication_flag` to true, because with no active waiver on file the screening is presumed failed. Revocation does not retroactively cancel any future-dated `BOOKED` bookings for medical-clearance services — the contraindication gate is re-checked only at booking-create time, never after the fact. Waivers are listed through a flat collection filterable by `member_id` and `status`.

Two safety gates therefore guard every booking. First, booking **any** service requires that the member currently have an `ACTIVE` waiver on file; a booking attempt by a member with no active waiver is rejected with `ERR_WAIVER_REQUIRED` (HTTP 422). Second, booking a service whose `requires_medical_clearance` is true is blocked whenever the member's `contraindication_flag` is true, and rejected with `ERR_CONTRAINDICATION_BLOCK` (HTTP 422).

### 3.4. Memberships: Subscriptions, Billing Cycles, Freeze, and Upgrade

Membership plans are created by a `PlatformAdmin`. A `MembershipPlan` has a `tier` — one of `BASE`, `PLUS`, or `ELITE`, unique across plans (a create that reuses an existing plan `tier` is rejected with `ERR_INVALID_REQUEST`, HTTP 400) — a `monthly_fee_cents` of at least 0, a `monthly_credit_grant` of service credits granted at the start of each billing cycle, a `rollover_cap` bounding how many unused granted credits carry into the next cycle (defaulting to 0, meaning no rollover), a `late_cancel_fee_waived` perk that when true makes late-cancel and no-show fees zero for that tier (defaulting to false, and intended for `ELITE`), and an `active` flag that when false prevents the plan from being subscribed to (defaulting to true).

A member starts a subscription by naming a `plan_id`; the action may be performed by the `Member` or a `LocationManager`. A member may hold only one live subscription at a time: starting a new subscription while a non-`CANCELLED` subscription already exists is rejected with `ERR_DUPLICATE_SUBSCRIPTION` (HTTP 409). On a successful start, the subscription is created `ACTIVE`, its `cycle_anchor_at` is set to the current clock, its `granted_credits_remaining` is set to the plan's `monthly_credit_grant`, a `SIGNUP` invoice for the plan's `monthly_fee_cents` is appended in `PAID` status, and the member's `credit_balance` is recomputed. The subscription also carries a `member_id`, a `plan_id`, a `freeze_cycles_remaining` that is 0 while `ACTIVE`, the computed `current_cycle_end_at`, and the computed `lifetime_paid_cents`.

**The billing cycle is thirty days long.** The recurring-billing driver is an idempotent administrative capability run by a `PlatformAdmin`: for a fixed clock it produces the same result no matter how many times it runs, and it reports how many subscriptions were renewed, how many were unfrozen, and how many packs expired. Its response `data` object carries exactly these three integer counts, keyed `subscriptions_renewed`, `subscriptions_unfrozen`, and `packs_expired`. It walks every subscription whose clock has reached or passed its `current_cycle_end_at` and acts according to status, and it also expires credit packs as described in Section 3.6.

For an `ACTIVE` subscription whose clock has reached or passed `current_cycle_end_at`, billing performs a **renewal**, a cyclic self-transition from `ACTIVE` back to `ACTIVE`: it appends a `RENEWAL` invoice for the plan's `monthly_fee_cents` in `PAID` status; it advances `cycle_anchor_at` to the previous `current_cycle_end_at` and recomputes `current_cycle_end_at`; it replenishes `granted_credits_remaining` to the plan's `monthly_credit_grant` plus the carried-over credits, where the carried amount is the smaller of the plan's `rollover_cap` and the prior `granted_credits_remaining`; and it recomputes the member's `credit_balance` and the subscription's `lifetime_paid_cents`.

A member may **freeze** an `ACTIVE` subscription for a whole number of upcoming cycles. The freeze request carries `freeze_cycles`, which must be an integer between 1 and 3 inclusive; a value outside that range is rejected with `ERR_FREEZE_CYCLES_INVALID` (HTTP 400). Freezing is permitted only while the subscription is `ACTIVE` and only when the member has no `BOOKED` booking whose `starts_at` falls within the frozen window. On freeze, the subscription moves to `FROZEN`, `freeze_cycles_remaining` is set to `freeze_cycles`, `granted_credits_remaining` is set to 0 because frozen cycles grant no credits, and the member's `credit_balance` is recomputed. While a subscription is `FROZEN` and the clock reaches or passes `current_cycle_end_at` with more than one frozen cycle still remaining, billing appends a `FREEZE_FEE` invoice of 1000 cents (ten dollars) in `PAID` status, advances `cycle_anchor_at` by one cycle and recomputes `current_cycle_end_at`, decrements `freeze_cycles_remaining` by one, and recomputes the subscription's `lifetime_paid_cents`; this is the `FROZEN`-to-`FROZEN` self-transition.

A frozen subscription returns to service in one of two ways. A member (or `LocationManager`) may **unfreeze** it manually, which is permitted only while `FROZEN`; alternatively, the billing driver auto-unfreezes a frozen subscription when its `freeze_cycles_remaining` reaches 0. Either path moves the subscription from `FROZEN` to `ACTIVE`, sets `freeze_cycles_remaining` to 0, re-anchors `cycle_anchor_at` to the current clock and recomputes `current_cycle_end_at`, restores `granted_credits_remaining` to the plan's `monthly_credit_grant`, and recomputes the member's `credit_balance`.

A member (or `LocationManager`) may **cancel** a subscription from either live state. Cancelling from `ACTIVE` moves it to `CANCELLED`, zeroes `granted_credits_remaining`, and recomputes the member's `credit_balance`. Cancelling from `FROZEN` moves it to `CANCELLED`, zeroes `freeze_cycles_remaining`, and recomputes the member's `credit_balance`. `CANCELLED` is terminal.

**Subscription refund quote.** A member or `LocationManager` may ask for a non-mutating refund quote on the current cycle, which returns both the provisional and final figures together with the day counts. The cycle is thirty days. The whole number of days elapsed since the cycle started is the floor of the difference between the current clock and `cycle_anchor_at` measured in whole days; the remaining days are thirty minus the elapsed days. The quote returns `elapsed_days`, `remaining_days`, a `provisional_remaining_cents`, and a `final_daily_floor_cents`. The **provisional** figure is the plan's `monthly_fee_cents` multiplied by the remaining days divided by thirty, rounded half up at that single step. The **final** figure — the amount that would actually be credited on a cancel commit — first floors the plan's `monthly_fee_cents` divided by thirty to obtain a whole-cent daily rate, then subtracts that daily rate multiplied by the elapsed days from the plan's `monthly_fee_cents`; this charges whole used days at the floored daily rate and diverges from the provisional figure by the rounding residue. The quote computes both variants over the single current cycle for the member's `ACTIVE` or `FROZEN` subscription. The quote is purely a read of the addressed subscription's stored `cycle_anchor_at` and applies no state-validity gate: it returns the computed figures for whatever subscription the path resolves to (including a `CANCELLED` one) and never raises `ERR_INVALID_STATE`.

**Subscription upgrade.** A member or `LocationManager` may upgrade an `ACTIVE` subscription to a higher-fee plan by naming the target `plan_id` and supplying `expected_subscription_version`. The target plan's `monthly_fee_cents` must be strictly greater than the current plan's; an equal or lower fee is rejected with `ERR_NOT_AN_UPGRADE` (HTTP 409). The proration charge is computed with a **load-bearing evaluation order** that must run before the cycle is re-anchored: first resolve the elapsed and remaining days from the current cycle anchor, where the cycle is thirty days, the elapsed days are the floor of the difference between the current clock and `cycle_anchor_at` in whole days, and the remaining days are thirty minus the elapsed days; then compute the fee delta as the target plan's `monthly_fee_cents` minus the current plan's `monthly_fee_cents` (which must be positive because only upgrades are allowed); then compute the proration as the fee delta multiplied by the remaining days divided by thirty, rounded half up at that single step; and only then re-anchor the cycle. Re-anchoring first would zero the remaining days and make the proration zero, which is why the order is fixed. On upgrade the server appends an `UPGRADE_PRORATION` invoice for the prorated amount in `PAID` status, points the subscription's `plan_id` at the new plan, re-anchors `cycle_anchor_at` to the current clock and recomputes `current_cycle_end_at`, sets `granted_credits_remaining` to the new plan's `monthly_credit_grant`, increments the subscription's `version` by one, and recomputes the member's `credit_balance` and `lifetime_paid_cents`. Because upgrade is OCC-guarded, a supplied `expected_subscription_version` that does not equal the subscription's current `version` is rejected with `ERR_STALE_VERSION` before any of this proceeds.

Every invoice carries an `id`, a `created_at`, a `subscription_id`, a `kind` of `SIGNUP`, `RENEWAL`, `UPGRADE_PRORATION`, or `FREEZE_FEE`, an `amount_cents`, and a `status` that is always `PAID` (invoices are paid at issue and the collection is append-only). Invoices are listed filterable by `subscription_id`, `kind`, and `status`.

### 3.5. Booking a Session

Booking is the heart of the system and the operation with the most gates. A booking is created by a `Member` (for themselves) or a `LocationManager` (on a member's behalf) with a `member_id`, a `location_id`, a `room_id`, a `starts_at` (the inclusive session start, ISO 8601 UTC), and the OCC field `expected_room_version`. The `member_id`, `location_id`, and `room_id` carried in this body are body foreign-key references: each is resolved per Section 2.7, and the first that does not resolve to an existing resource is rejected with `ERR_REFERENCE_NOT_FOUND` (HTTP 404), checked in that order after the member-ownership step. On success the booking copies its `service_type_id` from the chosen room, computes the interval it occupies, debits the credits, and is created `BOOKED`; the booking carries `member_id`, `location_id`, `room_id`, `service_type_id`, `starts_at`, the computed `occupies_until_at`, `credits_charged`, `credit_source`, `fee_charged_cents` (0 at creation), and `status`. Creating a booking increments the room's `version` by one, increments the owning location's `open_booking_count`, and recomputes the member's `credit_balance`. Bookings are listed filterable by `member_id`, `location_id`, `room_id`, `service_type_id`, and `status`.

The interval a booking occupies is the half-open span beginning at `starts_at` and running up to but not including `occupies_until_at`, where `occupies_until_at` is `starts_at` plus the service's `duration_minutes` plus the service's `buffer_minutes`. The room is considered occupied across that whole span, buffer included.

A booking-create request is evaluated through a sequence of gates after the foundational checks of Section 2.8. The location must be `OPEN`, or the request fails with `ERR_LOCATION_CLOSED` (HTTP 409). The room's `ServiceType` must have `active` true, or the request fails with `ERR_SERVICE_INACTIVE` (HTTP 409). The member must hold an `ACTIVE` waiver, or the request fails with `ERR_WAIVER_REQUIRED` (HTTP 422); and if the room's service has `requires_medical_clearance` true while the member's `contraindication_flag` is true, the request fails with `ERR_CONTRAINDICATION_BLOCK` (HTTP 422). The requested half-open interval must not intersect any existing `BOOKED` booking's interval on the same room — buffer included on both sides — or the request fails with `ERR_ROOM_UNAVAILABLE` (HTTP 409); intervals that merely touch at an endpoint do not overlap. The booking's occupied interval must be fully covered by at least one `SCHEDULED` technician shift at the booking's location, or the request fails with `ERR_NO_TECHNICIAN_ON_DUTY` (HTTP 409). Finally, the credit waterfall must be able to cover the service's `credit_cost`, or the request fails with `ERR_INSUFFICIENT_CREDITS` (HTTP 422) and no credits are debited.

**The credit waterfall.** The credits debited for a booking equal the service's `credit_cost`, and they are drawn from the member's wallets in a pinned bucket order. The system first takes from the subscription's granted credits: the amount taken from the subscription is the smaller of the cost and the subscription's `granted_credits_remaining` when the subscription is `ACTIVE`, or zero when there is no active subscription. The remainder after the subscription draw is then taken from the member's `ACTIVE` credit packs, considered in order of their `expires_at` ascending, breaking ties by `created_at` ascending — never by `id`. From each pack in turn the system takes the smaller of the still-remaining need and that pack's `remaining_credits`, decrementing the pack and the need, and stops once the need reaches zero. If after exhausting the subscription grant and all active packs the need is still above zero, the booking is rejected for insufficient credits with no debit applied. The booking records the source it drew from in `credit_source`: `SUBSCRIPTION` when the entire cost came from the subscription, `PACK` when none came from the subscription, and `SPLIT` when it drew partly from each. Whenever a pack's last remaining credit is consumed, that pack transitions from `ACTIVE` to `DEPLETED`.

After a session, a `Technician` (on a covering shift) or a `LocationManager` disposes of the booking. **Completing** a session is permitted only while the booking is `BOOKED`, only when the acting technician has a `SCHEDULED` shift at the booking's location covering the booking's `starts_at`, and only once the clock has reached or passed the booking's `starts_at`; it moves the booking from `BOOKED` to `COMPLETED` and decrements the location's `open_booking_count`. The covering-shift requirement is enforced only when the acting role is `Technician` and is treated as part of the Technician ownership model of Section 2.1 (a technician may dispose of a session only while standing on one of their own covering shifts): when a `Technician` completes a booking with no such `SCHEDULED` covering shift, the request is rejected with `ERR_FORBIDDEN` (HTTP 403) at the ownership step of the validation order; a `LocationManager` completing on the member's behalf is not subject to this covering-shift check. **Marking a no-show** is permitted only while the booking is `BOOKED` and only once the clock has reached or passed the booking's `starts_at`; unlike completion, it imposes no covering-shift ownership check, so any `Technician` (not only one standing on a `SCHEDULED` covering shift) or a `LocationManager` may mark a no-show once those two gates pass. It moves the booking from `BOOKED` to `NO_SHOW`, assesses the fee in no-show mode (see Section 3.7), forfeits the consumed credits (a no-show does not refund the session credits), and decrements the location's `open_booking_count`.

**Cancellation** is a member action (or `LocationManager` proxy) permitted only while the booking is `BOOKED` and only while the clock is still strictly before the booking's `starts_at`. It moves the booking from `BOOKED` to `CANCELLED`, assesses the late-cancel fee in cancel mode (see Section 3.7), refunds the charged credits to their original source, recomputes the member's `credit_balance`, and decrements the location's `open_booking_count`. The credit refund returns the charged credits to where they came from: the portion originally taken from the subscription is added back to the subscription's `granted_credits_remaining` first, up to what was taken from it, and any remainder is returned to the originating credit pack — except that any pack now in `REFUNDED`, `DEPLETED`, or `EXPIRED` status is skipped and that portion of the refund is forfeited.

### 3.6. Credit Packs and the Intro Offer

A member buys prepaid service credits in a `CreditPack`, purchased by the `Member` or a `LocationManager`. A purchase names `total_credits` (at least 1) and an `is_intro` flag marking whether this is the one-time discounted introductory pack. A new pack is `ACTIVE` with `remaining_credits` equal to `total_credits`, a computed `price_paid_cents`, and an `expires_at` set to the current clock plus its validity window; it also carries a `member_id`. **A credit pack is valid for 180 days** from purchase, after which its remaining credits expire. A member may buy the intro pack at most once: a purchase with `is_intro` true when the member's `intro_offer_used` is already true is rejected with `ERR_INTRO_ALREADY_USED` (HTTP 409). When an intro pack is purchased successfully, the member's `intro_offer_used` is set to true. Every purchase recomputes the member's `credit_balance`. Packs are listed filterable by `member_id` and `status`.

**Pack pricing has a pinned rounding order.** The list price is 2195 cents per credit, the intro discount is 30 percent (applied only when `is_intro` is true; otherwise the discount is zero), and a platform fee of 8 percent is applied at the end. The per-credit discounted price is computed first and rounded half up at the line-item level: it is 2195 multiplied by one minus the discount fraction, rounded. The subtotal is then that rounded per-credit price multiplied by `total_credits`. Finally the platform fee is applied to the subtotal — the subtotal multiplied by one plus 0.08 — and rounded half up once, yielding `price_paid_cents`. The order is round-per-credit, then sum, then apply the fee and round once; computing a subtotal as list price times the discount factor times the credit count and rounding only at the end is the wrong order and is forbidden, because it diverges by the rounding residue.

A `LocationManager` may **refund** an `ACTIVE` credit pack that still has credits left. Refund is permitted only while the pack is `ACTIVE` and only while its `remaining_credits` is above zero. The refund amount depends on whether the pack is an intro pack. First the system computes the average price per credit as the pack's `price_paid_cents` divided by its `total_credits`, rounded half up. For a non-intro pack, the refund is that per-credit average multiplied by the `remaining_credits` — refunding the unused credits at the average price. For an intro pack (`is_intro` true), the discount is forfeited on refund: the refund is the pack's `price_paid_cents` minus the per-credit average multiplied by the consumed credits, where the consumed credits are `total_credits` minus `remaining_credits`; this returns total paid minus consumed-at-average and differs from the non-intro figure by the rounding residue times the discount. On refund the pack's `remaining_credits` is set to 0, its status moves from `ACTIVE` to `REFUNDED`, and the member's `credit_balance` is recomputed.

Credit packs reach their other terminal states automatically. A pack moves from `ACTIVE` to `DEPLETED` the moment a booking consumes its last remaining credit. A pack moves from `ACTIVE` to `EXPIRED` when the billing driver runs and the clock has reached or passed the pack's `expires_at`: its `remaining_credits` is zeroed and the member's `credit_balance` is recomputed. `DEPLETED`, `REFUNDED`, and `EXPIRED` are all terminal.

**Member credit balance.** A member's `credit_balance` is reconciled as the subscription's `granted_credits_remaining` when the member has a subscription in `ACTIVE` or `FROZEN` status (and zero otherwise), plus the sum of `remaining_credits` across all of the member's credit packs whose status is `ACTIVE`. The balance is never negative. This reconciliation runs on any change to the subscription's `granted_credits_remaining` or to any pack's `remaining_credits` or status.

### 3.7. Cancellation and No-Show Fees

The late-cancel and no-show penalty is computed from a single rule with two modes. The constants are a free-cancellation window of 240 minutes (four hours), a base fee of 2000 cents, a late rate of 1500 cents per hour, and a fee cap of 5000 cents.

The notice in minutes is the floor of the difference between the booking's `starts_at` and the current clock, measured in whole minutes; in cancel mode this is at least zero (a member may only cancel before the start), and in no-show mode it is treated as zero. Three branches then apply, in this order. First, if the member's active plan tier has `late_cancel_fee_waived` true, the fee is 0. Otherwise, in cancel mode only, if the notice is at least the free-cancellation window of 240 minutes, the fee is 0. Otherwise the fee is computed: the hours short is the difference between 240 minutes and the notice minutes, divided by 60 and rounded up to a whole number (so a no-show, with zero notice, is four hours short); the fee is then the base fee of 2000 cents plus the late rate of 1500 cents multiplied by the hours short, capped at the fee cap of 5000 cents — that is, the smaller of 5000 and the computed sum. The result is recorded in the booking's `fee_charged_cents`.

## 4. Endpoint Definitions

Operations that create a brand-new resource return a `201 Created` status code. Operations that modify, transition, or otherwise act on an existing resource — including state transitions, refunds, and the administrative clock and billing capabilities — return a `200 OK` status code. List and single-resource reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock to a UTC instant | PlatformAdmin |
| POST | `/_billing/run` | Advance recurring billing and expire packs | PlatformAdmin |
| POST | `/locations` | Create a lounge location | PlatformAdmin |
| GET | `/locations` | List locations | PlatformAdmin, LocationManager, Member, Technician |
| GET | `/locations/{location_id}` | Get a location | PlatformAdmin, LocationManager, Member, Technician |
| POST | `/locations/{location_id}/close` | Close a location | PlatformAdmin, LocationManager |
| POST | `/locations/{location_id}/open` | Re-open a closed location | PlatformAdmin, LocationManager |
| POST | `/service-types` | Create a service-menu entry | PlatformAdmin |
| GET | `/service-types` | List the service menu | PlatformAdmin, LocationManager, Member, Technician |
| GET | `/service-types/{service_type_id}` | Get a service type | PlatformAdmin, LocationManager, Member, Technician |
| POST | `/locations/{location_id}/rooms` | Create a room at a location | PlatformAdmin, LocationManager |
| GET | `/rooms` | List rooms (filterable) | PlatformAdmin, LocationManager, Member, Technician |
| GET | `/rooms/{room_id}` | Get a room | PlatformAdmin, LocationManager, Member, Technician |
| POST | `/locations/{location_id}/technicians` | Register a technician at a location | PlatformAdmin, LocationManager |
| GET | `/technicians` | List technicians (filterable) | PlatformAdmin, LocationManager, Technician |
| GET | `/technicians/{technician_id}` | Get a technician | PlatformAdmin, LocationManager, Technician |
| POST | `/technicians/{technician_id}/shifts` | Add a shift to a technician's schedule | PlatformAdmin, LocationManager |
| GET | `/shifts` | List shifts (filterable) | PlatformAdmin, LocationManager, Technician |
| GET | `/shifts/{shift_id}` | Get a shift | PlatformAdmin, LocationManager, Technician |
| POST | `/shifts/{shift_id}/cancel` | Cancel a scheduled shift | PlatformAdmin, LocationManager |
| POST | `/membership-plans` | Create a membership plan tier | PlatformAdmin |
| GET | `/membership-plans` | List membership plans | PlatformAdmin, LocationManager, Member |
| GET | `/membership-plans/{plan_id}` | Get a membership plan | PlatformAdmin, LocationManager, Member |
| POST | `/members` | Register a member | PlatformAdmin, LocationManager |
| GET | `/members` | List members (filterable) | PlatformAdmin, LocationManager |
| GET | `/members/{member_id}` | Get a member | PlatformAdmin, LocationManager, Member |
| POST | `/members/{member_id}/waivers` | Sign a waiver / submit screening | Member, LocationManager |
| GET | `/waivers` | List waivers (filterable) | PlatformAdmin, LocationManager, Member |
| GET | `/waivers/{waiver_id}` | Get a waiver | PlatformAdmin, LocationManager, Member |
| POST | `/members/{member_id}/waivers/{waiver_id}/revoke` | Revoke a member's active waiver | LocationManager |
| POST | `/members/{member_id}/subscription` | Start a subscription | Member, LocationManager |
| GET | `/subscriptions` | List subscriptions (filterable) | PlatformAdmin, LocationManager, Member |
| GET | `/subscriptions/{subscription_id}` | Get a subscription | PlatformAdmin, LocationManager, Member |
| GET | `/subscriptions/{subscription_id}/refund-quote` | Get both refund variants for the current cycle | Member, LocationManager |
| POST | `/subscriptions/{subscription_id}/upgrade` | Upgrade to a higher-fee plan (OCC-guarded) | Member, LocationManager |
| POST | `/subscriptions/{subscription_id}/freeze` | Freeze the subscription for N cycles | Member, LocationManager |
| POST | `/subscriptions/{subscription_id}/unfreeze` | Manually unfreeze a frozen subscription | Member, LocationManager |
| POST | `/subscriptions/{subscription_id}/cancel` | Cancel the subscription | Member, LocationManager |
| GET | `/invoices` | List invoices (filterable) | PlatformAdmin, LocationManager, Member |
| GET | `/invoices/{invoice_id}` | Get an invoice | PlatformAdmin, LocationManager, Member |
| POST | `/members/{member_id}/credit-packs` | Purchase a credit pack | Member, LocationManager |
| GET | `/credit-packs` | List credit packs (filterable) | PlatformAdmin, LocationManager, Member |
| GET | `/credit-packs/{pack_id}` | Get a credit pack | PlatformAdmin, LocationManager, Member |
| POST | `/members/{member_id}/credit-packs/{pack_id}/refund` | Refund an active credit pack | LocationManager |
| POST | `/bookings` | Book a session (OCC-guarded on room) | Member, LocationManager |
| GET | `/bookings` | List bookings (filterable) | PlatformAdmin, LocationManager, Technician, Member |
| GET | `/bookings/{booking_id}` | Get a booking | PlatformAdmin, LocationManager, Technician, Member |
| POST | `/bookings/{booking_id}/cancel` | Cancel a future booking | Member, LocationManager |
| POST | `/bookings/{booking_id}/complete` | Mark a session completed | Technician, LocationManager |
| POST | `/bookings/{booking_id}/no-show` | Mark a member no-show | Technician, LocationManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CONTRAINDICATION_BLOCK` | 422 Unprocessable Entity |
| `ERR_WAIVER_REQUIRED` | 422 Unprocessable Entity |
| `ERR_ROOM_UNAVAILABLE` | 409 Conflict |
| `ERR_SHIFT_OVERLAP` | 409 Conflict |
| `ERR_NO_TECHNICIAN_ON_DUTY` | 409 Conflict |
| `ERR_INTRO_ALREADY_USED` | 409 Conflict |
| `ERR_NOT_AN_UPGRADE` | 409 Conflict |
| `ERR_INSUFFICIENT_CREDITS` | 422 Unprocessable Entity |
| `ERR_LOCATION_CLOSED` | 409 Conflict |
| `ERR_SERVICE_INACTIVE` | 409 Conflict |
| `ERR_FREEZE_CYCLES_INVALID` | 400 Bad Request |
| `ERR_VALIDATION_PAGINATION` | 400 Bad Request |
| `ERR_DUPLICATE_SUBSCRIPTION` | 409 Conflict |

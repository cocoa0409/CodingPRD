# Apartment Leasing API — Product Requirements Document

## 1. Introduction

A leasing office wins or loses its month at the top of the funnel. Prospects arrive as walk-ins, phone calls, web-form submissions, ILS listings, and referrals; the speed of the first response, the ease of getting a tour on the calendar, and the honesty of the price on display all determine whether that traffic becomes a signed lease. Behind the scenes, the office juggles agent calendars, concession budgets, screening policy, property-specific lease addenda, utility transfers, and the politics of a waitlist for a sold-out floorplan — while ownership asks which agents and which lead sources actually close.

This document specifies the Apartment Leasing API, a single service governing the full conversion pipeline: inquiry intake with per-property response-time targets, guided and self-guided tour scheduling against agent availability, pricing and concession offers with defined display windows, rental applications with screening-driven approval conditions, lease generation with applicant e-signature, move-in scheduling with utility-transfer gating and first-period proration, a floorplan waitlist with timed offers, and closing-ratio reporting by agent and source. All leasing resources are mounted under `/leasing`. The API serves three actors — property managers, leasing agents, and applicants — and runs on a controllable logical clock so that offer expirations, signing deadlines, waitlist offer windows, and response-time targets are all evaluated deterministically rather than against wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, conventions, and cross-cutting principles that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the caller's operational capacity. The system recognizes exactly three roles: `PropertyManager`, `LeasingAgent`, and `Applicant`. A request missing either header, or carrying a role outside this set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Once authenticated, each endpoint permits only the roles listed in §4; a caller whose role is not permitted is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Role identity is bound to persisted entities, and the binding differs by role. When `X-User-Role` is `PropertyManager`, `X-User-ID` is the `id` of the acting `Agent` — a manager's agent record — and ownership checks on any resource that references an `Agent` (such as an inquiry's assigned agent) compare that field to `X-User-ID`; a `PropertyManager` may perform every operation a `LeasingAgent` can, and is additionally exempt from the assigned-agent ownership checks described below. When `X-User-Role` is `LeasingAgent`, `X-User-ID` is likewise the `id` of the acting `Agent`, and ownership checks compare it directly. When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the `Application` the portal session is scoped to: the applicant may read property, floorplan, and pricing-offer display data, read application and lease records — these reads are not ownership-scoped, so any `Applicant` context may read any application or lease — and e-sign their lease, with the signature check comparing the lease's application reference to `X-User-ID`.

Two ownership rules deserve emphasis. Recording a first response or marking an inquiry lost requires the caller to be the inquiry's assigned agent or a `PropertyManager`; anyone else is rejected with `ERR_NOT_ASSIGNED_AGENT` (HTTP 403). Signing a lease requires the caller's `X-User-ID` to equal the lease's application reference; a mismatch is rejected with `ERR_APPLICANT_MISMATCH` (HTTP 403).

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

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_` followed by twenty random alphanumeric characters.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read from wall-clock time — the envelope's only use of wall clock, since every business timestamp derives from the logical clock of §2.4.
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

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; when omitted it defaults to 10, and it accepts values from a minimum of 1 to a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. A `limit` or `offset` that is not an integer, a `limit` outside that range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order, with timestamps that tie broken by creation order (earliest created first).

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset + limit` is less than `total_count`.

### 2.4. The Logical Leasing Clock and Lazy Expiry

All deadlines, expiries, and service-level computations in the system read a single server-side logical clock; the system never falls back to wall-clock time. Every business timestamp the server writes — `created_at`, `updated_at`, `first_responded_at`, `signed_at`, `executed_at`, deadlines, and offer expirations — is stamped from this logical clock. At server startup, before any adjustment, the logical clock reads exactly 2026-08-01T00:00:00Z. A `PropertyManager` may advance or set the clock through a dedicated test-driving capability that accepts a `to_iso8601` instant in ISO 8601 UTC; the response echoes the new logical time as `current_utc`, and every subsequent deadline evaluation — offer expiry, lease signing deadlines, waitlist offer windows, response-time measurement — reads the new time.

Expiry in this system is lazy rather than pushed by a scheduler. A pricing offer whose `expires_at` has been reached becomes `EXPIRED` the next time the offer is read or any operation references it; a lease whose `signing_deadline` has been reached becomes `EXPIRED` on its next read or reference; and a waitlist entry whose `offer_expires_at` has been reached is swept back to the queue on its next access. Each of these lazy transitions carries the side effects described in §3 — the pricing display falls back to base rent, an expired lease leaves the committed-unit set, and an expired waitlist offer requeues to the back of the line.

### 2.5. Common Resource Properties

Every resource in the system — Property, Agent, Floorplan, PricingOffer, Inquiry, Tour, WaitlistEntry, Application, Lease, and MoveIn — carries a uniform set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp recording when the resource was created; like every datetime the API emits inside `data`, it is serialized with three fractional digits when the value carries sub-second precision and in the compact whole-second form (e.g. `2026-08-01T00:00:00Z`) otherwise.
- `updated_at` (string): an ISO 8601 UTC timestamp, serialized the same way, refreshed on any change to the resource.
- `version` (integer): a system-managed integer that starts at 1 on creation and increments on every mutation of the resource.

This convention gives every entity a consistent audit trail and provides the `version` values that the concurrency rule in §2.8 relies upon.

### 2.6. Rent Arithmetic and Precision

All monetary values in the system are integer counts of cents. Rent computations — the effective monthly rent on a pricing offer, the pinned rent on an application or lease, the rent-override floor, and the first-period proration on a move-in — produce whole cents with no decimal places, using round-half-up whenever a division or percentage produces a fraction. Screening and deposit math is integer-cent comparison with no rounding at all. The closing-ratio report is the one non-monetary exception to whole-number output: its percentages are rounded half-up to one decimal place. Response-time measurement truncates to whole minutes.

One rounding rule is pinned by contract because the alternative produces different cents: when prorating, the daily rate is rounded to whole cents first, and only then multiplied by the number of occupied days. Multiplying first and rounding the product is not used.

### 2.7. The Unit Availability Ledger

Each floorplan carries two computed counters that act as the property's availability ledger. `committed_units` counts the floorplan's leases whose status is `ISSUED`, `SIGNED_BY_APPLICANT`, or `EXECUTED` — a lease joins the committed set the moment it is generated, not when it is signed. `available_units` is `total_units` minus `committed_units`. A freshly created floorplan starts with `committed_units` at zero, so `available_units` equals `total_units`.

The ledger is recomputed immediately on every event that changes the committed set: lease generation (a new `ISSUED` lease enters), lease supersession (the departing lease leaves exactly as its replacement enters, for a net change of zero), lease countersignature (the lease already counted since issuance, so the count is refreshed but unchanged), lease expiry and lease cancellation (the lease leaves and `available_units` rises by one). Because availability drives waitlist auto-promotion and self-guided tour booking, every one of these recomputations happens as part of the triggering operation, never in a batch.

### 2.8. Optimistic Concurrency Control on Lease Generation

Lease generation is the single write operation in the API guarded by optimistic concurrency control. A generation request must carry `expected_application_version`, holding the `version` of the application as the client last observed it; the field is not optional. If the application's current `version` no longer matches the submitted value — because another write has advanced the application since the client last read it — the generation is rejected with `ERR_STALE_VERSION` (HTTP 412), and no lease is created. The reason is specific to this workflow: regeneration legitimately supersedes a prior `ISSUED` lease for the same application, so a writer holding a stale application version would otherwise supersede a lease it never observed. The check is a stale-version comparison on the application's `version`, evaluated for strictly sequential requests. No endpoint other than lease generation accepts a version field. A successful generation itself advances the application's `version` by one.

### 2.9. Cross-Entity State Cascades

State changes propagate across entity boundaries in two well-defined chains, and smaller cascades around them. The conversion chain fires when a lease is countersigned: the lease reaches `EXECUTED`, its application advances to `LEASED`, the application’s source inquiry advances to `CONVERTED`, and every tour still `SCHEDULED` for that inquiry is cancelled — the prospect has signed, so remaining appointments are moot. The unwind chain fires when a lease is cancelled: the lease leaves the committed set and `available_units` rises, every `SCHEDULED` or `READY` move-in of the lease is cancelled, the freed unit triggers auto-promotion of the waitlist queue head when effective availability permits, and — only when the cancelled lease was `EXECUTED` — the application compensates from `LEASED` back to `APPROVED`. Independently, marking an inquiry `LOST` cancels all of its `SCHEDULED` tours, and tour-level outcomes (cancellation or no-show) revert the inquiry from `TOUR_SCHEDULED` to `CONTACTED` when no scheduled tour remains. Each cascade is atomic with its triggering operation, and each mutation updates the affected resource's `updated_at` and increments its `version`.

### 2.10. Validation Order and Reference Integrity

The API surface is flat: every endpoint carries at most one path identifier and there is no URL nesting, so references between resources travel in request bodies as foreign-key fields. Every request is validated in a fixed order, and the first failing check determines the response.

First, authentication context: the two headers must be present and the role recognized, otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Second, authorization and ownership: the role must be permitted on the endpoint (`ERR_UNAUTHORIZED_ROLE`), the respond and mark-lost ownership check (`ERR_NOT_ASSIGNED_AGENT`), and the lease-signature identity check (`ERR_APPLICANT_MISMATCH`). Third, existence and request shape: path identifiers are resolved and each body reference must point at an existing resource — a missing property, agent, floorplan, pricing offer, inquiry, tour, waitlist entry, application, lease, or move-in surfaces `ERR_PROPERTY_NOT_FOUND`, `ERR_AGENT_NOT_FOUND`, `ERR_FLOORPLAN_NOT_FOUND`, `ERR_PRICING_OFFER_NOT_FOUND`, `ERR_INQUIRY_NOT_FOUND`, `ERR_TOUR_NOT_FOUND`, `ERR_WAITLIST_ENTRY_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, or `ERR_MOVE_IN_NOT_FOUND` respectively; malformed payloads — a missing required field, an invalid enum member, a negative or otherwise invalid numeric, a malformed datetime, or a conditional-field violation such as an `agent_id` attached to a `SELF_GUIDED` tour or missing from a `GUIDED` one — fail with `ERR_INVALID_REQUEST`; an application payload carrying both or neither of its two source references fails with `ERR_APPLICATION_SOURCE_AMBIGUOUS`. Fourth, state checks: the per-entity invalid-state family (`ERR_INQUIRY_INVALID_STATE`, `ERR_TOUR_INVALID_STATE`, `ERR_WAITLIST_INVALID_STATE`, `ERR_APPLICATION_INVALID_STATE`, `ERR_LEASE_INVALID_STATE`, `ERR_MOVEIN_INVALID_STATE`, `ERR_PRICING_OFFER_INVALID_STATE`), the pipeline-gating errors (`ERR_INQUIRY_NOT_ACTIVE`, `ERR_APPLICATION_NOT_LEASABLE`, `ERR_LEASE_NOT_EXECUTED`), the utility-transfer gate (`ERR_UTILITY_CONFIRMATION_REQUIRED`), a repeat first response (`ERR_ALREADY_RESPONDED`), and the stale-version rejection (`ERR_STALE_VERSION`). Fifth, the screening gate (`ERR_SCREENING_BLOCKS_APPROVAL`). Sixth, uniqueness and availability constraints: one published offer per floorplan (`ERR_OFFER_ALREADY_PUBLISHED`), one active move-in per lease (`ERR_MOVEIN_ALREADY_ACTIVE`), waitlist join only when the floorplan is sold out (`ERR_FLOORPLAN_AVAILABLE`), self-guided tours only with a unit available (`ERR_SELF_GUIDED_NO_UNIT`), promotion only of the queue head (`ERR_NOT_QUEUE_HEAD`) with a unit to offer (`ERR_NO_UNITS_TO_OFFER`), and no lease regeneration once a lease is committed (`ERR_LEASE_ALREADY_COMMITTED`). Seventh, interval and capacity rules: agent calendar conflicts (`ERR_TOUR_TIME_CONFLICT`), the daily move-in cap (`ERR_MOVEIN_DAY_FULL`), and end-after-start window rules (`ERR_INVALID_TIME_RANGE`). Eighth, cross-reference integrity: an application must match its source's floorplan (`ERR_APPLICATION_FLOORPLAN_MISMATCH`) and a lease's selected offer must belong to the application's floorplan (`ERR_OFFER_FLOORPLAN_MISMATCH`). Ninth and last, money checks: the deposit payment must cover the requirement (`ERR_DEPOSIT_INSUFFICIENT`) and a rent override must clear its floor (`ERR_RENT_OVERRIDE_TOO_LOW`). Because the order is fixed, a request that would fail two checks always reports the earlier one — a mid-flight state problem surfaces before a money problem, and a missing resource before either.

## 3. Business Logic & Workflows

### 3.1. Setting Up Properties, Agents, and Floorplans

Everything begins with configuration, which is exclusively `PropertyManager` work. Creating a property takes a display `name` and a `code` that must be unique across all properties — a duplicate `code` is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — plus the leasing configuration that drives the rest of the pipeline. `response_time_target_minutes` sets the first-response service target and defaults to 60 minutes. `tour_buffer_minutes`, defaulting to 15, is the minimum turnaround the system requires between one agent's tours. `self_guided_window_minutes`, defaulting to 60, fixes the access-window length granted to self-guided visitors. `max_moveins_per_day`, defaulting to 2, caps aggregate move-in volume per UTC calendar date at the property. `utility_transfer_required`, defaulting to true, decides whether a move-in may complete without a confirmed utility transfer. `prorate_method` selects how first-period rent is prorated: `CALENDAR` prorates by the actual days in the move-in month, `FIXED_30` prorates by thirty-day months, and the default is `CALENDAR`. Finally, `required_addenda` lists the addendum codes that must be snapshotted onto every lease the property generates; it defaults to an empty list.

Agents are created with a `full_name`, an `email`, the `property_id` of their home property, and two knobs: `max_concurrent_tours`, the maximum number of overlapping guided tours the agent may hold, defaulting to 1, and `active`, defaulting to true. An inactive agent cannot be assigned new inquiries or tours; such an assignment attempt is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The agent roster can be listed with a `property_id` filter.

Floorplans are created per property with `property_id`, a `name` such as "A2 - 1BR/1BA", a `bedrooms` count, the list rent `base_rent_cents` in cents before any concession, and the physical unit count `total_units`. The computed counters arrive with the floorplan: `committed_units` begins at zero and `available_units` begins equal to `total_units`, thereafter maintained by the availability ledger of §2.7. Floorplans can be listed with a `property_id` filter, and reading a single floorplan always reflects the current committed and available counts.

### 3.2. Publishing Pricing and Concessions

A pricing offer is how a property advertises a deal against a floorplan. A `PropertyManager` creates one with `property_id`, `floorplan_id`, the offer's `base_rent_cents`, a display window from `effective_start` to `expires_at`, and concession details. The window must be a genuine interval: an `expires_at` that does not fall strictly after `effective_start` is rejected with `ERR_INVALID_TIME_RANGE` (HTTP 400). `concession_type` is one of `NONE`, `FLAT_AMOUNT`, `PERCENT_OFF`, or `FREE_MONTHS`, defaulting to `NONE`; `concession_value` defaults to 0 and means cents for a flat amount, a percentage between 0 and 100 for a percent-off deal, or a count of months for a free-months deal — a negative value, or a percentage above 100 on a `PERCENT_OFF` offer, is rejected with `ERR_INVALID_REQUEST` (HTTP 400); `lease_term_months`, defaulting to 12 and required to be at least 1, is the term over which free months are amortized.

The offer's displayed price, `effective_monthly_rent_cents`, is computed at creation and stored on the offer. With a `NONE` concession the effective rent equals `base_rent_cents`. With `FLAT_AMOUNT` it is `base_rent_cents` minus `concession_value` cents, never below zero. With `PERCENT_OFF` it is `base_rent_cents` multiplied by the remaining percentage — one hundred minus `concession_value`, over one hundred — rounded half-up to whole cents. With `FREE_MONTHS`, the billed-month count is `lease_term_months` minus the smaller of `concession_value` and `lease_term_months`, never below zero, and the effective rent is `base_rent_cents` multiplied by the billed months and divided by `lease_term_months`, rounded half-up to whole cents.

Offers are born `DRAFT`. Publishing one requires it to be `DRAFT` (anything else is `ERR_PRICING_OFFER_INVALID_STATE`), requires that no other offer for the same floorplan currently be `PUBLISHED` (`ERR_OFFER_ALREADY_PUBLISHED`), and requires its `expires_at` to lie strictly after the current logical time — publishing an already-lapsed offer is rejected with `ERR_INVALID_TIME_RANGE`. Retiring works from either `DRAFT` or `PUBLISHED` and lands the offer in the terminal `RETIRED` state. When the logical clock reaches a published offer's `expires_at`, the offer expires lazily per §2.4, landing in the terminal `EXPIRED` state, and the floorplan's pricing display falls back to the floorplan's `base_rent_cents` for subsequent reads and calculations. Offers can be listed with `property_id`, `floorplan_id`, and `status` filters, and any read of the collection or of a single offer performs the lazy expiry sweep first.

### 3.3. From First Inquiry to Toured Prospect

An inquiry is the guest card at the top of the funnel. A `LeasingAgent` or `PropertyManager` creates one with the `property_id`, an optional `floorplan_id` naming the floorplan of interest, the prospect's `contact_name` and `contact_email`, and the lead `source` — one of `WALK_IN`, `PHONE`, `WEB_FORM`, `ILS_LISTING`, or `REFERRAL`. New inquiries arrive `NEW` with `assigned_agent_id`, `first_responded_at`, and `response_met_target` all still null. Inquiries can be listed with `property_id`, `floorplan_id`, `assigned_agent_id`, `status`, and `source` filters.

Claiming assigns the card: `assigned_agent_id` becomes the caller's agent id (for a `PropertyManager` caller, their own agent record), while the status is unchanged. Only an unassigned inquiry in `NEW`, `CONTACTED`, or `TOUR_SCHEDULED` can be claimed; a terminal inquiry or an already-assigned one is rejected with `ERR_INQUIRY_INVALID_STATE`.

The first response is the moment the service target is measured. Responding is permitted exactly once, from `NEW`: a repeat response on an inquiry already `CONTACTED` or `TOUR_SCHEDULED` is rejected with `ERR_ALREADY_RESPONDED`, responding on a terminal (`LOST` or `CONVERTED`) inquiry or an unassigned one is rejected with `ERR_INQUIRY_INVALID_STATE`, and a caller who is neither the assigned agent nor a `PropertyManager` is rejected with `ERR_NOT_ASSIGNED_AGENT`. A successful response stamps `first_responded_at` with the current logical time, moves the inquiry to `CONTACTED`, and computes `response_met_target`: the elapsed whole minutes between the inquiry's `created_at` and `first_responded_at`, truncated to whole minutes, is compared against the property's `response_time_target_minutes`, and a response landing at exactly the target counts as met.

Tours put the prospect on site. Booking one takes `inquiry_id`, `tour_type` (`GUIDED` or `SELF_GUIDED`), and `scheduled_start`. For a `GUIDED` tour an `agent_id` is required and the client supplies `scheduled_end`, which must fall strictly after `scheduled_start` (`ERR_INVALID_TIME_RANGE`). For a `SELF_GUIDED` tour `agent_id` must be omitted, and the server computes `scheduled_end` as `scheduled_start` plus the property's `self_guided_window_minutes`, ignoring any client-supplied value; mixing the fields up — an agent on a self-guided tour or none on a guided one — is an `ERR_INVALID_REQUEST`. A self-guided booking additionally requires the floorplan of interest to have at least one unit available; while that floorplan's `available_units` is zero, the request is rejected with `ERR_SELF_GUIDED_NO_UNIT` (an inquiry carrying no `floorplan_id` is exempt from this check). Booking against an inquiry in `LOST` or `CONVERTED` is rejected with `ERR_INQUIRY_NOT_ACTIVE`, whatever the tour type. A new tour starts `SCHEDULED`; when the inquiry is `CONTACTED`, creating the tour advances it to `TOUR_SCHEDULED` automatically.

Guided tours contend for the agent's calendar; self-guided tours carry no agent and never occupy a calendar. Each scheduled guided tour blocks the half-open interval from its `scheduled_start` to its `scheduled_end` plus the property's `tour_buffer_minutes` of turnaround after the tour, and an agent may hold at most `max_concurrent_tours` overlapping blocked intervals; a guided booking whose blocked window would collide with the blocked windows of `max_concurrent_tours` or more of the agent's existing `SCHEDULED` tours is rejected with `ERR_TOUR_TIME_CONFLICT`. Because the blocked intervals are half-open, a gap of exactly `tour_buffer_minutes` between two tours is allowed. Rescheduling is a self-loop from `SCHEDULED` back to `SCHEDULED`: the client submits a new `scheduled_start` and, for guided tours, a new `scheduled_end`, the tour's interval is replaced, the inquiry stays `TOUR_SCHEDULED`, and the new interval must pass the same availability rules as creation — the conflict check (with the tour's own previous interval not counting against it), the self-guided unit check, and the end-after-start check all apply again. A tour that is no longer `SCHEDULED` cannot be rescheduled (`ERR_TOUR_INVALID_STATE`).

Recording an outcome takes an `outcome` of `COMPLETED` or `NO_SHOW`, from `SCHEDULED` only (`ERR_TOUR_INVALID_STATE`). The two outcomes differ in their cross-entity effect: a plain completion leaves the inquiry where it is, while a `NO_SHOW` reverts the inquiry from `TOUR_SCHEDULED` to `CONTACTED` when no other `SCHEDULED` tour remains for it. Cancelling a tour — by an agent, or as part of the mark-lost and conversion cascades — likewise requires the tour to be `SCHEDULED`, and the cascades simply skip tours that no longer are. Cancellation carries the same reversion as a no-show: the inquiry drops back from `TOUR_SCHEDULED` to `CONTACTED` when no other scheduled tour remains, but only while the inquiry is still `TOUR_SCHEDULED`; once an inquiry has reached `CONVERTED` or `LOST` it never reverts. Tours can be listed with `inquiry_id`, `agent_id`, and `status` filters.

Marking an inquiry lost is permitted from `NEW`, `CONTACTED`, or `TOUR_SCHEDULED` — from anywhere else it is `ERR_INQUIRY_INVALID_STATE` — and only by the assigned agent or a `PropertyManager` (`ERR_NOT_ASSIGNED_AGENT`). The inquiry lands in the terminal `LOST` state, and the loss cascades: every `SCHEDULED` tour of the inquiry is cancelled. Conversion is the happy mirror image and never happens by request: when a lease for an application born of the inquiry reaches `EXECUTED`, an inquiry in `CONTACTED` or `TOUR_SCHEDULED` becomes `CONVERTED` automatically, and its remaining `SCHEDULED` tours are cancelled because the prospect has signed.

### 3.4. The Waitlist: Queueing for a Sold-Out Floorplan

When a floorplan has no units to show, prospects queue. Joining the waitlist takes `floorplan_id`, `contact_name`, and `contact_email`, and is permitted only while the floorplan's `available_units` is zero; joining while at least one unit is available is rejected with `ERR_FLOORPLAN_AVAILABLE`. A new entry starts `WAITING` with `offer_expires_at` and `linked_application_id` null, and its `position` is computed as one more than the highest `position` among the floorplan's other entries in `WAITING` or `OFFERED` — the entry being created is excluded from that maximum — or 1 when no such entries exist. Positions are never reused: entries that reach `CONVERTED` or `CANCELLED` keep their historical positions.

Promotion offers a unit to the queue head, whether an agent triggers it directly or the system auto-promotes when a unit frees through a lease cancellation or expiry. The queue head is the `WAITING` entry for the floorplan with the smallest `position`, ties broken by the earliest `created_at` and any remaining ties by creation order; when no `WAITING` entry exists there is no head, auto-promotion is a no-op, and a targeted promotion of a non-head entry is rejected with `ERR_NOT_QUEUE_HEAD`. The entry being promoted must be `WAITING` (`ERR_WAITLIST_INVALID_STATE` otherwise), and promotion requires effective availability — the floorplan's `available_units` minus the number of its entries currently `OFFERED` — of at least one, otherwise `ERR_NO_UNITS_TO_OFFER`. A promoted entry becomes `OFFERED`, and its `offer_expires_at` is set to the current logical time plus a seventy-two-hour offer window.

An offer resolves in one of four ways. The prospect accepts implicitly by applying: when an application is created naming the entry, the entry must be `OFFERED` and unexpired (`ERR_WAITLIST_INVALID_STATE` otherwise), and it becomes `CONVERTED` with its `linked_application_id` set to the new application's id. The prospect declines: the entry returns from `OFFERED` to `WAITING`, its `offer_expires_at` is cleared to null, and its `position` is recomputed to the back of the queue — one more than the highest position among the floorplan's other `WAITING` or `OFFERED` entries. The offer lapses: once the logical clock reaches `offer_expires_at`, the entry is lazily swept back to `WAITING` on its next access, with the same requeue-to-back and cleared expiry. Or the entry is cancelled: cancellation is permitted from `WAITING` or `OFFERED` (anything else is `ERR_WAITLIST_INVALID_STATE`), lands the entry in the terminal `CANCELLED` state, and clears `offer_expires_at` when cancelling an `OFFERED` entry. Waitlist entries can be listed with `floorplan_id`, `status`, and `linked_application_id` filters, and reads perform the lazy offer-expiry sweep first.

### 3.5. Applications, Screening, and Approval Conditions

An application is opened from exactly one source: an `inquiry_id` or a `waitlist_entry_id`. Supplying both, or neither, is rejected with `ERR_APPLICATION_SOURCE_AMBIGUOUS` (HTTP 400). An inquiry-sourced application requires the inquiry to be in `CONTACTED` or `TOUR_SCHEDULED` — a fresh or terminal inquiry yields `ERR_INQUIRY_NOT_ACTIVE` — while a waitlist-sourced application requires the entry `OFFERED` and unexpired (`ERR_WAITLIST_INVALID_STATE`). In both cases the payload's `floorplan_id` must equal the source's floorplan; a mismatch is rejected with `ERR_APPLICATION_FLOORPLAN_MISMATCH` (HTTP 422). The applicant's file is captured as `applicant_name`, `applicant_email`, `annual_income_cents` (verified gross annual income in cents), and `credit_score` (300 to 850). Applications can be listed with `floorplan_id`, `inquiry_id`, `waitlist_entry_id`, and `status` filters.

At creation the server pins `monthly_rent_snapshot_cents`: when the floorplan has a `PUBLISHED` offer, the snapshot is that offer's `effective_monthly_rent_cents`; otherwise it is the floorplan's `base_rent_cents`. From that snapshot the server derives the screening `recommendation`. Income qualifies when `annual_income_cents` is at least three times the annualized rent — three times twelve times `monthly_rent_snapshot_cents` — and income landing exactly at that threshold qualifies. When income qualifies and `credit_score` is at least 700, the recommendation is `APPROVE`, with a score of exactly 700 eligible. When income qualifies and the score is at least 620 but below 700, the recommendation is `CONDITION`, with exactly 620 landing here. In every other case — income short of the threshold, or a score below 620 — the recommendation is `DENY`. A new application starts in `SCREENING` with `required_deposit_cents` null and `deposit_paid_cents` at 0.

Decision-making belongs to the `PropertyManager`, who submits a `decision` of `APPROVED`, `APPROVED_WITH_CONDITIONS`, or `DENIED` against an application in `SCREENING` (any other state is `ERR_APPLICATION_INVALID_STATE`). The screening gate stands between recommendation and decision: deciding `APPROVED` or `APPROVED_WITH_CONDITIONS` while the recommendation is `DENY` is rejected with `ERR_SCREENING_BLOCKS_APPROVAL` (HTTP 422) — no approval may override a denial recommendation. A decision of `APPROVED` sets `required_deposit_cents` to one month of the snapshot rent; `APPROVED_WITH_CONDITIONS` sets it to two months of the snapshot rent; `DENIED` is terminal and sets no deposit.

Conditional approvals have two ways forward. A `PropertyManager` may re-screen the application with fresh `annual_income_cents` and `credit_score`, cycling it from `APPROVED_WITH_CONDITIONS` back to `SCREENING`: the recommendation is recomputed from the new figures against the unchanged `monthly_rent_snapshot_cents` — re-screening does not re-resolve the offer — `required_deposit_cents` resets to null, and the accumulated `deposit_paid_cents` resets to 0. Alternatively, a `LeasingAgent` or `PropertyManager` records a condition-clearing payment by submitting `deposit_paid_cents`; the payment is added to the accumulated paid total, and when the total reaches at least `required_deposit_cents` the application advances to `CONDITIONS_CLEARED`. A payment that would leave the accumulated total below the requirement is rejected with `ERR_DEPOSIT_INSUFFICIENT` (HTTP 402). Withdrawal is permitted from `SCREENING` or `APPROVED_WITH_CONDITIONS` and lands the application in the terminal `WITHDRAWN` state; from anywhere else the request is `ERR_APPLICATION_INVALID_STATE`. Once a lease for the application reaches `EXECUTED`, the application — whether `APPROVED` or `CONDITIONS_CLEARED` — becomes `LEASED`, terminal, and that transition is what fires the inquiry conversion described in §3.3.

### 3.6. Lease Generation, Signature, and Execution

Lease generation is `PropertyManager` work, guarded by the optimistic-concurrency rule of §2.8: the request names the `application_id` and must carry `expected_application_version`, and a stale read is rejected with `ERR_STALE_VERSION`. The application must be `APPROVED` or `CONDITIONS_CLEARED`; anything else is `ERR_APPLICATION_NOT_LEASABLE`. The request may select a `pricing_offer_id`, which must be `PUBLISHED` at generation time (a draft, retired, or expired offer is `ERR_PRICING_OFFER_INVALID_STATE`) and must belong to the application's floorplan (otherwise `ERR_OFFER_FLOORPLAN_MISMATCH`, HTTP 422). The request may also carry a `rent_override_cents`.

The lease pins `monthly_rent_cents` by a fixed precedence: a valid `rent_override_cents` wins; otherwise the selected published offer's `effective_monthly_rent_cents`; with no offer selected, the floorplan's `base_rent_cents`. An override is valid only when it reaches at least eighty percent of the rent that would otherwise be pinned, with that floor computed and rounded half-up to whole cents; a lower override is rejected with `ERR_RENT_OVERRIDE_TOO_LOW` (HTTP 422). Each generated lease copies its `floorplan_id` from the application, snapshots `deposit_cents` from the application's `required_deposit_cents`, snapshots `addenda_codes` from the property's `required_addenda` — addenda vary by property, so the lease freezes them at generation — and sets `signing_deadline` to forty-eight hours after creation. The lease is born `ISSUED` with `signed_at`, `executed_at`, and `superseded_by_id` null, and counts toward the floorplan's committed units from that moment. Generation also increments the application's `version` by one, which is why the OCC field must reflect the client's latest read.

Regeneration is the deliberate do-over. When a prior lease for the same application is still `ISSUED`, generating a new lease supersedes it: the old lease becomes `SUPERSEDED` with `superseded_by_id` pointing at the new lease, and because the departing lease leaves the committed set exactly as the new `ISSUED` lease enters it, `committed_units` nets out unchanged. Regeneration is blocked entirely once any lease for the application has reached `SIGNED_BY_APPLICANT` or `EXECUTED` — the parties are already committed, and the request is rejected with `ERR_LEASE_ALREADY_COMMITTED`.

Signature is the applicant's act, and the only operation the `Applicant` role can write. Signing requires the lease to be `ISSUED` (any other state is `ERR_LEASE_INVALID_STATE`), requires the current logical time to fall strictly before `signing_deadline` — at or past the deadline the lease is treated as `EXPIRED` and the signing attempt is likewise rejected with `ERR_LEASE_INVALID_STATE` — and requires the caller's `X-User-ID` to equal the lease's `application_id`, with a mismatch rejected as `ERR_APPLICANT_MISMATCH`. A successful signature stamps `signed_at` and moves the lease to `SIGNED_BY_APPLICANT`. A lease that passes its deadline unsigned expires lazily per §2.4: it leaves the committed set, the floorplan's `committed_units` is recomputed, and the freed unit may trigger auto-promotion of the waitlist queue head.

The countersignature completes the deal. A `PropertyManager` countersigns a lease in `SIGNED_BY_APPLICANT` (any other state is `ERR_LEASE_INVALID_STATE`); the lease becomes `EXECUTED`, `executed_at` is stamped with the current logical time, and the conversion chain of §2.9 fires: the application advances to `LEASED`, the source inquiry becomes `CONVERTED`, and that inquiry's remaining `SCHEDULED` tours are cancelled. The floorplan's committed count is recomputed, unchanged, since the lease has counted since issuance.

Cancellation unwinds in proportion to how far the lease had progressed. A `PropertyManager` may cancel from `ISSUED`, `SIGNED_BY_APPLICANT`, or `EXECUTED` — from any other state it is `ERR_LEASE_INVALID_STATE`. In all three cases the lease leaves the committed set (`committed_units` is recomputed and `available_units` rises by one), every `SCHEDULED` or `READY` move-in of the lease is cancelled, and the freed unit triggers auto-promotion of the waitlist queue head when effective availability is at least one. Cancelling an `EXECUTED` lease adds the compensation step: the application returns from `LEASED` to `APPROVED` with its `required_deposit_cents` retained, becoming leasable again. Leases can be listed with `application_id`, `floorplan_id`, and `status` filters, and reads perform the lazy expiry sweep first.

### 3.7. Move-In Day: Scheduling, Utilities, and Prorated Rent

With an `EXECUTED` lease in hand, an agent schedules the move-in by submitting the `lease_id` and a `scheduled_date` whose day bucket is read as a UTC calendar date. Scheduling against a lease in any other state is rejected with `ERR_LEASE_NOT_EXECUTED`. Two capacity rules guard the day. A lease supports at most one active move-in — one in `SCHEDULED` or `READY` — and a second attempt is rejected with `ERR_MOVEIN_ALREADY_ACTIVE`. And when the count of `SCHEDULED` or `READY` move-ins already on that UTC date at the lease's property has reached the property's `max_moveins_per_day`, the request is rejected with `ERR_MOVEIN_DAY_FULL`.

A new move-in starts `SCHEDULED` with `utility_confirmed` false, and the server computes `prorated_rent_cents` — the first-period prorated rent — from the executed lease's pinned `monthly_rent_cents`, the `scheduled_date`, and the property's `prorate_method`. The rounding order is the pinned one from §2.6: the daily rate is rounded half-up to whole cents first, then multiplied by the occupied-day count. Under `CALENDAR`, the divisor is the actual number of days in the calendar month of `scheduled_date` — anywhere from 28 to 31 — and the occupied-day count is that divisor minus the move-in's day of month plus one, so the move-in day itself counts. Under `FIXED_30`, the divisor is always 30, the day of month is clamped at 30 — a move-in on the 31st is treated as the 30th and occupies exactly one day — and the occupied-day count is 30 minus the clamped day plus one. In both cases the prorated rent is the rounded daily rate multiplied by the occupied-day count.

Utility transfer gates completion where the property demands it. Confirming utilities advances the move-in from `SCHEDULED` to `READY` and sets `utility_confirmed` true; from any other state the confirmation is `ERR_MOVEIN_INVALID_STATE`. Completing the move-in is always permitted from `READY`. Completing directly from `SCHEDULED` is permitted only when the property's `utility_transfer_required` is false; such a direct completion leaves `utility_confirmed` false. When the property requires the transfer, a direct completion is rejected with `ERR_UTILITY_CONFIRMATION_REQUIRED`, and attempts from any state other than `READY` or an eligible `SCHEDULED` are `ERR_MOVEIN_INVALID_STATE`. Cancellation is permitted from `SCHEDULED` or `READY` — anything else is `ERR_MOVEIN_INVALID_STATE` — and a lease cancellation cancels the lease's active move-ins outright, as part of the unwind chain of §2.9. Move-ins can be listed with `lease_id` and `status` filters.

### 3.8. Measuring Conversion: The Closing Report

Ownership reads the funnel through the closing report, which is computed on read and never stored. The report is requested with a `property_id` and a window from `window_start` to `window_end`, plus an optional `basis` — `ALL` by default, or `QUALIFIED` — and optional `agent_id` and `source` filters. The window is half-open: an inquiry enters the report when its `created_at` falls at or after `window_start` and strictly before `window_end`. Only inquiries with a non-null `assigned_agent_id` participate, and they are grouped by assigned agent and lead `source`.

Within each group, the closed count is the number of inquiries whose status is `CONVERTED`. Under basis `ALL`, the denominator counts every assigned inquiry of the group inside the window, even ones never contacted. Under basis `QUALIFIED`, the denominator counts only group inquiries with a recorded `first_responded_at`, so the qualified basis produces a strictly larger ratio whenever uncontacted inquiries exist in the window. The reported ratio, `closing_ratio_pct`, is one hundred times the closed count divided by the denominator, rounded half-up to one decimal place, and groups whose denominator is zero are omitted from the response entirely. The response is a single object, not a paginated list: it echoes the request's `property_id`, `window_start`, `window_end`, and `basis`, and carries the computed `rows`, where each row carries `agent_id`, `source`, `inquiries_count` (the group's denominator), `closed_count`, and `closing_ratio_pct`, and rows are ordered by `agent_id` and then `source`, both ascending.

## 4. Endpoint Definitions

Operations that create a new resource — a property, agent, floorplan, pricing offer, inquiry, tour, waitlist entry, application, lease, or move-in — return `201 Created`. Operations that modify an existing resource, and all reads, return `200 OK`. The complete request and response semantics of each operation are defined by the workflows in §3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/leasing/properties` | Create a property with its leasing configuration | PropertyManager |
| GET | `/leasing/properties` | List properties (paginated) | PropertyManager, LeasingAgent, Applicant |
| GET | `/leasing/properties/{propertyId}` | Get a property | PropertyManager, LeasingAgent, Applicant |
| POST | `/leasing/agents` | Create a leasing agent | PropertyManager |
| GET | `/leasing/agents` | List agents; filterable by property | PropertyManager, LeasingAgent |
| GET | `/leasing/agents/{agentId}` | Get an agent | PropertyManager, LeasingAgent |
| POST | `/leasing/floorplans` | Create a floorplan for a property | PropertyManager |
| GET | `/leasing/floorplans` | List floorplans; filterable by property | PropertyManager, LeasingAgent, Applicant |
| GET | `/leasing/floorplans/{floorplanId}` | Get a floorplan with computed unit counts | PropertyManager, LeasingAgent, Applicant |
| POST | `/leasing/pricing-offers` | Create a pricing/concession offer in DRAFT | PropertyManager |
| GET | `/leasing/pricing-offers` | List pricing offers; filterable by property, floorplan, status | PropertyManager, LeasingAgent, Applicant |
| GET | `/leasing/pricing-offers/{pricingOfferId}` | Get a pricing offer | PropertyManager, LeasingAgent, Applicant |
| POST | `/leasing/pricing-offers/{pricingOfferId}/publish` | Publish a DRAFT offer; at most one PUBLISHED per floorplan | PropertyManager |
| POST | `/leasing/pricing-offers/{pricingOfferId}/retire` | Retire a DRAFT or PUBLISHED offer | PropertyManager |
| POST | `/leasing/inquiries` | Create an inquiry (guest card) with source tracking | PropertyManager, LeasingAgent |
| GET | `/leasing/inquiries` | List inquiries; filterable by property, floorplan, agent, status, source | PropertyManager, LeasingAgent |
| GET | `/leasing/inquiries/{inquiryId}` | Get an inquiry | PropertyManager, LeasingAgent |
| POST | `/leasing/inquiries/{inquiryId}/claim` | Assign the inquiry to the calling agent | LeasingAgent, PropertyManager |
| POST | `/leasing/inquiries/{inquiryId}/respond` | Record first response; NEW → CONTACTED; computes SLA flag | LeasingAgent, PropertyManager |
| POST | `/leasing/inquiries/{inquiryId}/mark-lost` | Mark inquiry LOST; cancels its SCHEDULED tours | LeasingAgent, PropertyManager |
| POST | `/leasing/tours` | Schedule a guided or self-guided tour with availability sync | LeasingAgent, PropertyManager |
| GET | `/leasing/tours` | List tours; filterable by inquiry, agent, status | PropertyManager, LeasingAgent |
| GET | `/leasing/tours/{tourId}` | Get a tour | PropertyManager, LeasingAgent |
| POST | `/leasing/tours/{tourId}/reschedule` | Reschedule a SCHEDULED tour with full availability revalidation | LeasingAgent, PropertyManager |
| POST | `/leasing/tours/{tourId}/complete` | Record tour outcome: COMPLETED or NO_SHOW | LeasingAgent, PropertyManager |
| POST | `/leasing/tours/{tourId}/cancel` | Cancel a SCHEDULED tour | LeasingAgent, PropertyManager |
| POST | `/leasing/waitlist-entries` | Join the waitlist for a sold-out floorplan | LeasingAgent, PropertyManager |
| GET | `/leasing/waitlist-entries` | List waitlist entries; filterable by floorplan, status, linked application | PropertyManager, LeasingAgent |
| GET | `/leasing/waitlist-entries/{entryId}` | Get a waitlist entry | PropertyManager, LeasingAgent |
| POST | `/leasing/waitlist-entries/{entryId}/promote` | Offer a unit to the queue head; WAITING → OFFERED | LeasingAgent, PropertyManager |
| POST | `/leasing/waitlist-entries/{entryId}/decline` | Record offer decline; entry requeues to the back | LeasingAgent, PropertyManager |
| POST | `/leasing/waitlist-entries/{entryId}/cancel` | Remove an entry from the waitlist | LeasingAgent, PropertyManager |
| POST | `/leasing/applications` | Create an application from an inquiry or offered waitlist entry | LeasingAgent, PropertyManager |
| GET | `/leasing/applications` | List applications; filterable by floorplan, inquiry, waitlist entry, status | PropertyManager, LeasingAgent |
| GET | `/leasing/applications/{applicationId}` | Get an application | PropertyManager, LeasingAgent, Applicant |
| POST | `/leasing/applications/{applicationId}/decide` | Decide: APPROVED, APPROVED_WITH_CONDITIONS, or DENIED | PropertyManager |
| POST | `/leasing/applications/{applicationId}/rescreen` | Re-screen an APPROVED_WITH_CONDITIONS application with updated financials | PropertyManager |
| POST | `/leasing/applications/{applicationId}/clear-conditions` | Record a condition-clearing deposit payment | LeasingAgent, PropertyManager |
| POST | `/leasing/applications/{applicationId}/withdraw` | Withdraw a SCREENING or APPROVED_WITH_CONDITIONS application | LeasingAgent, PropertyManager |
| POST | `/leasing/leases` | Generate a lease for an APPROVED / CONDITIONS_CLEARED application | PropertyManager |
| GET | `/leasing/leases` | List leases; filterable by application, floorplan, status | PropertyManager, LeasingAgent |
| GET | `/leasing/leases/{leaseId}` | Get a lease | PropertyManager, LeasingAgent, Applicant |
| POST | `/leasing/leases/{leaseId}/sign` | Applicant e-signature | Applicant |
| POST | `/leasing/leases/{leaseId}/countersign` | PropertyManager countersignature → EXECUTED; fires the conversion cascade | PropertyManager |
| POST | `/leasing/leases/{leaseId}/cancel` | Cancel a non-terminal lease; frees the unit and unwinds dependents | PropertyManager |
| POST | `/leasing/move-ins` | Schedule a move-in for an EXECUTED lease | LeasingAgent, PropertyManager |
| GET | `/leasing/move-ins` | List move-ins; filterable by lease, status | PropertyManager, LeasingAgent |
| GET | `/leasing/move-ins/{moveInId}` | Get a move-in | PropertyManager, LeasingAgent |
| POST | `/leasing/move-ins/{moveInId}/confirm-utilities` | Confirm utility transfer; SCHEDULED → READY | LeasingAgent, PropertyManager |
| POST | `/leasing/move-ins/{moveInId}/complete` | Complete the move-in | LeasingAgent, PropertyManager |
| POST | `/leasing/move-ins/{moveInId}/cancel` | Cancel a SCHEDULED/READY move-in | LeasingAgent, PropertyManager |
| GET | `/leasing/reports/closing` | Closing ratio by agent and source; basis ALL or QUALIFIED | PropertyManager, LeasingAgent |
| POST | `/_clock/set_current_utc` | Set the logical clock (ISO 8601 UTC) | PropertyManager |

## 5. Error Code Catalogue

The table below enumerates every domain error identifier and its HTTP status. The conditions that trigger each error are defined in the narratives of §2 and §3. Two further identifiers sit outside the domain flows: a request to an unrecognized path is rejected with `ERR_NOT_FOUND` (HTTP 404), and an unexpected server failure surfaces `ERR_INTERNAL` (HTTP 500), both in the standard error envelope.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_NOT_ASSIGNED_AGENT` | 403 Forbidden |
| `ERR_APPLICANT_MISMATCH` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_PROPERTY_NOT_FOUND` | 404 Not Found |
| `ERR_AGENT_NOT_FOUND` | 404 Not Found |
| `ERR_FLOORPLAN_NOT_FOUND` | 404 Not Found |
| `ERR_PRICING_OFFER_NOT_FOUND` | 404 Not Found |
| `ERR_INQUIRY_NOT_FOUND` | 404 Not Found |
| `ERR_TOUR_NOT_FOUND` | 404 Not Found |
| `ERR_WAITLIST_ENTRY_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_LEASE_NOT_FOUND` | 404 Not Found |
| `ERR_MOVE_IN_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_TIME_RANGE` | 400 Bad Request |
| `ERR_APPLICATION_SOURCE_AMBIGUOUS` | 400 Bad Request |
| `ERR_INQUIRY_INVALID_STATE` | 409 Conflict |
| `ERR_INQUIRY_NOT_ACTIVE` | 409 Conflict |
| `ERR_ALREADY_RESPONDED` | 409 Conflict |
| `ERR_TOUR_INVALID_STATE` | 409 Conflict |
| `ERR_TOUR_TIME_CONFLICT` | 409 Conflict |
| `ERR_SELF_GUIDED_NO_UNIT` | 409 Conflict |
| `ERR_PRICING_OFFER_INVALID_STATE` | 409 Conflict |
| `ERR_OFFER_ALREADY_PUBLISHED` | 409 Conflict |
| `ERR_WAITLIST_INVALID_STATE` | 409 Conflict |
| `ERR_FLOORPLAN_AVAILABLE` | 409 Conflict |
| `ERR_NOT_QUEUE_HEAD` | 409 Conflict |
| `ERR_NO_UNITS_TO_OFFER` | 409 Conflict |
| `ERR_APPLICATION_INVALID_STATE` | 409 Conflict |
| `ERR_SCREENING_BLOCKS_APPROVAL` | 422 Unprocessable Entity |
| `ERR_APPLICATION_FLOORPLAN_MISMATCH` | 422 Unprocessable Entity |
| `ERR_APPLICATION_NOT_LEASABLE` | 409 Conflict |
| `ERR_DEPOSIT_INSUFFICIENT` | 402 Payment Required |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_LEASE_ALREADY_COMMITTED` | 409 Conflict |
| `ERR_OFFER_FLOORPLAN_MISMATCH` | 422 Unprocessable Entity |
| `ERR_RENT_OVERRIDE_TOO_LOW` | 422 Unprocessable Entity |
| `ERR_LEASE_INVALID_STATE` | 409 Conflict |
| `ERR_LEASE_NOT_EXECUTED` | 409 Conflict |
| `ERR_MOVEIN_DAY_FULL` | 409 Conflict |
| `ERR_MOVEIN_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_MOVEIN_INVALID_STATE` | 409 Conflict |
| `ERR_UTILITY_CONFIRMATION_REQUIRED` | 409 Conflict |

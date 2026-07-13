# Funeral Live-Stream & Tribute Service API — Product Requirements Document

## 1. Introduction

Families arranging a memorial service increasingly rely on a funeral home to broadcast the service to relatives who cannot attend in person, to host an online memorial page, and to produce a keepsake recording afterward. This API is the operational backbone for that offering. It lets a funeral home (the vendor) schedule a service, reserve a chapel or venue, stand up a multi-camera live stream with configurable audio, publish a private guest link, collect condolences and donations through a memorial page, and deliver an edited recording — all while a platform operator manages prepaid stream credits, settles donations, and reviews tribute videos.

The domain is unusually rich because a single service order carries several independent lifecycles that advance on their own timelines: the broadcast itself moves from planning to live to ended, the billing settlement runs on a separate track, the technical stream readiness is toggled by on-call operators, the post-production recording has its own edit-and-deliver flow, and the public memorial page is published and later archived. These axes evolve concurrently on the same record, and many operations reach across records — cancelling a service releases its venue holds, which in turn releases the camera crew; settling a donation reconciles running totals on both the order and the vendor account. The requirements below fix the exact contract for every one of these behaviors so that any compliant implementation produces identical results.

Because grief-stricken families and remote mourners are the ultimate consumers, the system treats privacy, correct billing, and reliable delivery as first-class concerns. Guest links can be password-protected and self-lock after repeated failed attempts; billing distinguishes a forward estimate from the final invoice computed against what actually aired; and every monetary figure is tracked in whole cents to avoid rounding drift.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are present and valid but the declared role is not permitted to invoke the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly four roles: `FuneralHome`, `Operator`, `PlatformAdmin`, and `Guest`.

- When `X-User-Role` is `FuneralHome`, `X-User-ID` is the `id` of the acting `FuneralHome` account. Ownership checks on any resource that references a funeral home compare the resource's `home_id` foreign key to `X-User-ID`; a mismatch is a cross-tenant access attempt.
- When `X-User-Role` is `Operator`, `X-User-ID` is the `id` of the acting `Operator`. An operator belongs to one funeral home, and ownership checks compare the target resource's `home_id` against that operator's own `home_id`; cross-tenant access is denied.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. A `PlatformAdmin` holds override authority across all tenants and is not subject to tenant-isolation checks; the server does not compare the value to any entity's `id`.
- When `X-User-Role` is `Guest`, `X-User-ID` is an opaque public-visitor identifier not tied to any persisted entity. A `Guest` acts only through a service order's guest link and is likewise not compared to any entity's `id`.

Any cross-tenant access — a `FuneralHome` or `Operator` acting on a resource whose `home_id` is not their own — is rejected with `ERR_CROSS_TENANT_FORBIDDEN`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. A supplied `limit` below 1 is clamped up to 1 and a `limit` above 100 is clamped down to 100; a negative `offset` is clamped to 0; a `limit` or `offset` that is not a valid integer is rejected with `ERR_VALIDATION`. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, all list endpoints return their resources sorted by `created_at` in ascending order, with ties on an identical `created_at` broken by ascending creation order (server insertion sequence). Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Every entity in this system — funeral homes, venues, operators, service orders, venue bookings, camera assignments, guestbook entries, donations, and tribute videos — carries a standard set of system-managed properties:

- `id`: a server-minted UUID with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, stamped when the resource is first created.
- `updated_at`: an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version`: an integer that starts at `1` on creation and increments by one on every mutation of the resource.

Whenever a computed or derived field on a resource changes as a consequence of some action — for example, a running donation total or a guest-entry count — that change is itself a mutation of the resource, so it refreshes `updated_at` and increments `version`.

### 2.5. Tenant Isolation and Left-to-Right Path Resolution

When an endpoint path names a resource by `id`, the server resolves that identifier first and rejects the request with the resource-specific not-found error if it does not exist — `ERR_FUNERAL_HOME_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`, `ERR_OPERATOR_NOT_FOUND`, `ERR_SERVICE_ORDER_NOT_FOUND`, `ERR_VENUE_BOOKING_NOT_FOUND`, `ERR_CAMERA_ASSIGNMENT_NOT_FOUND`, `ERR_GUESTBOOK_ENTRY_NOT_FOUND`, `ERR_DONATION_NOT_FOUND`, or `ERR_TRIBUTE_VIDEO_NOT_FOUND`. When a path or payload references multiple identifiers, they are validated left to right, and the first one that does not resolve determines the not-found error returned.

Once existence is confirmed, tenant isolation applies: a `FuneralHome` or `Operator` may only read or write resources whose `home_id` belongs to their own funeral home. A `PlatformAdmin` is exempt from this restriction. On list endpoints this isolation is applied as a silent filter rather than an error: a `FuneralHome` or `Operator` sees only resources of their own funeral home, so a `home_id` query filter naming a different tenant simply yields an empty page.

### 2.6. Validation Order and Precedence

Because several checks can apply to a single request, the order in which they are evaluated is part of the contract — the first check that fails determines the error returned. Requests are validated in this fixed precedence:

1. Authentication headers are present and valid (otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, HTTP 400).
2. The acting role is permitted to invoke the endpoint (otherwise `ERR_UNAUTHORIZED`, HTTP 403).
3. Every resource `id` named in the path exists, validated left to right (otherwise the matching not-found error, HTTP 404).
4. Tenant isolation holds for `FuneralHome` and `Operator` actors on owned resources (otherwise `ERR_CROSS_TENANT_FORBIDDEN`, HTTP 403).
5. Input shape is well-formed: required fields present and enums valid, time ranges ordered, camera count in range, donation amount positive (HTTP 422, see below).
6. The target resource or axis is in the correct state for the requested transition (HTTP 409, state-specific error).
7. Cross-entity readiness is satisfied — confirmed venue, ready stream, published memorial (HTTP 409, see §3).
8. The target operator is on duty when a camera assignment is created (otherwise `ERR_OPERATOR_OFF_DUTY`, HTTP 409).
9. No resource time conflict exists (HTTP 409, see §3).
10. The guest-link password is correct when the private link is attempted (otherwise `ERR_INVALID_ACCESS_PASSWORD`, HTTP 403).
11. The funeral home holds sufficient stream credits to schedule (otherwise `ERR_INSUFFICIENT_STREAM_CREDITS`, HTTP 402).
12. The optimistic-concurrency version check on venue reservation holds (otherwise `ERR_STALE_ORDER_VERSION`, HTTP 412).

The input-shape stage (priority 5) reports `ERR_VALIDATION` for a missing required field or an unrecognized enum value, `ERR_INVALID_TIME_RANGE` when an end instant is not strictly after its start, `ERR_INVALID_CAMERA_COUNT` when the camera count falls outside the permitted range, and `ERR_INVALID_DONATION_AMOUNT` when a pledged amount is not positive — all HTTP 422.

### 2.7. The Parallel Status Model of a Service Order

A service order is not governed by a single status field. It carries several independent status axes that advance on their own, and a transition on one axis never implicitly moves another:

- `broadcast_status` — the broadcast lifecycle: `DRAFT`, `SCHEDULED`, `LIVE`, `ENDED`, or `CANCELLED`.
- `settlement_status` — the billing lifecycle, independent of broadcast: `UNBILLED`, `INVOICED`, `PAID`, or `VOID`.
- `stream_status` — technical readiness set by operators: `PENDING`, `READY`, or `FAILED`.
- `recording_status` — post-production: `NONE`, `RAW`, `EDITING`, `READY`, or `DELIVERED`.
- `memorial_status` — the public memorial page: `DRAFT`, `PUBLISHED`, or `ARCHIVED`.

When an order is created, `broadcast_status` is `DRAFT`, `settlement_status` is `UNBILLED`, `stream_status` is `PENDING`, `recording_status` is `NONE`, and `memorial_status` is `DRAFT`. Cancellation is the terminal condition for the order as a whole; an order that has both aired (`ENDED`) and been paid (`PAID`) is the successful resting state.

### 2.8. Cascading Releases and Derived-Field Reconciliation

Some operations mutate more than one record. When a service order is cancelled, every venue booking of that order still in `HELD` or `CONFIRMED` is moved to `RELEASED`, and each such release in turn moves every `ASSIGNED` camera assignment of that order's crew to `RELEASED`. These cascades run automatically as part of the triggering operation; every record the cascade touches is a mutation, refreshing its `updated_at` and incrementing its `version`.

Several read-only totals are reconciled the moment their inputs change rather than being recomputed on read. A funeral home's `donations_pledged_cents` and `donations_net_cents`, an order's `donations_net_cents`, and an order's `guestbook_entry_count` are all derived aggregates; whenever an underlying donation or guestbook entry changes status, the affected aggregates are recomputed immediately and the owning record is mutated accordingly.

### 2.9. Optimistic Concurrency for Venue Reservations

Reserving a venue window for an order is guarded by optimistic concurrency control on the parent service order. A reservation request must carry `expected_order_version`, holding the client's last observed `version` of the target `ServiceOrder`. If that value does not equal the order's current `version` — meaning another writer has advanced the order since the client last read it — the reservation is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412). Because a new reservation legitimately supersedes any prior held booking for the same order and advances the order's `version`, this check prevents a client operating on a stale view from silently creating a duplicate reservation. Only the venue-reservation endpoint takes a version field; no other endpoint requires one.

### 2.10. Monetary Precision and the Cents Convention

All monetary quantities — stream billing, donation amounts, fees, and net totals — are integers denominated in cents; there are no fractional cents. Where a rule multiplies by a percentage and the intermediate result is not a whole number, the fee is rounded half up to the nearest cent before it is used, and each donation's fee is rounded individually before any totals are summed (the system never sums gross amounts and then applies a single fee). Stream billing tiers are computed entirely in integer cents, and the minute-based duration inputs are whole minutes.

### 2.11. The Logical Clock

The server keeps a logical clock that supplies the current UTC instant used to stamp when a broadcast actually starts and ends. Before any clock has been set, the logical clock reads `2026-03-01T00:00:00Z`, and it never falls back to wall-clock time. An administrator-only test-driving capability sets the clock to a supplied `to_iso8601` instant; going live and ending a broadcast both stamp their timestamps from this clock.

## 3. Business Logic & Workflows

### 3.1. Vendor Accounts and the Stream-Credit Ledger

A `PlatformAdmin` onboards a vendor by creating a funeral-home account, supplying the home's `name` and `contact_email` and, optionally, `initial_credits`. The account's prepaid balance, `stream_credit_balance`, is seeded from `initial_credits` (treated as zero when omitted), and its running donation totals — `donations_pledged_cents` and `donations_net_cents` — both begin at zero. A funeral home may read its own account; a `PlatformAdmin` may read any.

Stream credits are the currency that lets a home take a service live. A `PlatformAdmin` tops up a home by granting credits, supplying a `credit_amount` that is added to `stream_credit_balance`. Thereafter the balance moves only through the broadcast lifecycle: it decreases by one when an order is scheduled and increases by one when a scheduled order is subsequently cancelled, refunding the credit that scheduling consumed. Concretely, the balance equals the initial credits plus the sum of all granted amounts, minus one for each order currently holding a consumed credit, plus one for each scheduled order that was later cancelled. The balance is never allowed to fall below zero. As an invariant, scheduling an order and then immediately cancelling it leaves `stream_credit_balance` exactly where it was before scheduling.

### 3.2. Venues, Operators, and Duty Status

A funeral home defines the physical spaces it broadcasts from as **venues**. A venue is created with its parent `home_id`, a `name`, an in-person seating `capacity` (informational), and a `turnaround_minutes` cleanup buffer. The turnaround value matters later: it is the cushion applied on both sides of every reservation window when the system checks a venue for scheduling conflicts. Venues may be listed, optionally filtered by `home_id`, or fetched individually.

The technical crew are **operators**. An operator is created under a `home_id` with a `full_name` and a `skill`, which is one of `CAMERA`, `AUDIO`, or `SUPPORT`. Every operator starts `OFF_DUTY`; the operator's availability is tracked by `duty_status`, which is either `OFF_DUTY` or `ON_DUTY`. An operator can put themselves on or off shift by setting `duty_status`, and a funeral home or platform administrator may do the same on their behalf. Duty status is consequential because a camera assignment can only be created against an operator who is currently on duty.

### 3.3. Opening a Service Order

A funeral home opens a **service order** to memorialize a decedent. Creation requires the `home_id`, the `venue_id` of the chosen venue, the `decedent_name`, and the planned broadcast window given as `scheduled_start` and `scheduled_end`; the end must be strictly after the start, or the request is rejected with `ERR_INVALID_TIME_RANGE`. Several attributes are optional at creation with defined defaults: `expected_viewers` (an informational peak-audience estimate defaulting to zero), `priority_support` (a boolean, default false, that decides whether an on-call priority surcharge lands on the final invoice), `camera_count` (defaulting to one and constrained to between one and four inclusive, otherwise `ERR_INVALID_CAMERA_COUNT`), and `audio_source` (one of `HOUSE_SYSTEM`, `EXTERNAL_MIXER`, or `SINGLE_MIC`, defaulting to `HOUSE_SYSTEM`).

The same creation call configures the private guest link and the memorial page. The `privacy_mode` is one of `PUBLIC`, `PASSWORD`, or `INVITE_ONLY` and defaults to `PASSWORD`; when it is `PASSWORD`, the plaintext `access_password` is supplied and is otherwise null. The server mints an opaque `access_token` for the guest link and initializes `failed_access_count` to zero. Memorial-page fields — the `headline` text and the informational `donation_goal_cents` fundraising target (default zero) — may also be supplied, and the recording delivery address `delivery_email` may be set now or later. On creation the several status axes take their initial values described in §2.7. Orders may be listed, optionally filtered by `home_id` and `venue_id`, or fetched individually, at which point the read-only rollups `estimated_cost_cents`, `final_invoice_cents`, `recording_duration_minutes`, `access_locked`, `donations_net_cents`, and `guestbook_entry_count` reflect the order's current derived state. `estimated_cost_cents` is null until scheduling computes it and `final_invoice_cents` is null until invoicing computes it.

### 3.4. Reserving and Confirming the Venue

Before a service can be scheduled it needs a confirmed venue reservation. Reserving a venue for an order creates a **venue booking** from the `order_id`, the `venue_id`, and the reservation window `window_start` and `window_end` — the end strictly after the start, or `ERR_INVALID_TIME_RANGE`. The reservation must also carry `expected_order_version` for the optimistic-concurrency check described in §2.9. A new booking is born in `HELD` status, copies the order's `home_id`, advances the order's `version` by one, and moves any prior `HELD` booking of the same order to `RELEASED`, so an order never carries two competing holds.

At reservation time the system enforces venue exclusivity. A new booking window is expanded by the venue's `turnaround_minutes` on both sides, and if that expanded window intersects any existing `HELD` or `CONFIRMED` booking that belongs to a *different* service order on the same venue, the reservation is refused with `ERR_VENUE_TIME_CONFLICT`; the same order's own prior bookings are excluded from this check (they are instead superseded, as above). The intersection test is strict — windows that merely touch end-to-start do not conflict. Bookings may be listed with optional `order_id`, `venue_id`, and `home_id` filters, or fetched individually.

A held booking becomes firm when the funeral home confirms it, moving its `status` from `HELD` to `CONFIRMED`; confirming anything not currently `HELD` is rejected with `ERR_BOOKING_NOT_HELD`. Only a `CONFIRMED` booking satisfies the scheduling precondition in §3.6.

### 3.5. Staffing the Crew

A funeral home assigns operators to a service by creating **camera assignments**. An assignment names the `order_id`, the `operator_id`, and the crew `role` (one of `CAMERA`, `AUDIO`, or `SUPPORT`), copies the order's `home_id`, and starts in `ASSIGNED` status. Two guards run at creation. First, the target operator must be on duty; assigning an operator whose `duty_status` is not `ON_DUTY` is rejected with `ERR_OPERATOR_OFF_DUTY`. Second, the operator must be free during the service: an assignment covers its order's planned window from `scheduled_start` to `scheduled_end`, and if that window overlaps the window of any other `ASSIGNED` assignment for the same operator, the request is refused with `ERR_OPERATOR_TIME_CONFLICT`. This overlap check is strict and applies no buffer; two windows that merely touch end-to-start are treated as non-overlapping and are allowed. Assignments may be listed with optional `order_id`, `operator_id`, and `home_id` filters, or fetched individually. A camera assignment leaves `ASSIGNED` only when the system releases it — an assignment moves to `RELEASED` automatically as a downstream consequence of its order's venue bookings being released during an order cancellation.

### 3.6. The Broadcast Lifecycle

The broadcast axis is driven by the funeral home. Order transitions across every axis — broadcast, settlement, stream readiness, recording, and memorial — are all requested through a single transition operation whose `action` field names the specific step being taken. The recognized `action` values are exactly `SCHEDULE`, `GO_LIVE`, `END`, `CANCEL`, `INVOICE`, `PAY`, `SET_STREAM_READY`, `SET_STREAM_FAILED`, `START_EDIT`, `MARK_RECORDING_READY`, `DELIVER_RECORDING`, `PUBLISH_MEMORIAL`, and `ARCHIVE_MEMORIAL`; any other value is rejected with `ERR_VALIDATION`. Although the endpoint admits `FuneralHome`, `Operator`, and `PlatformAdmin`, authorization is refined per action: `FuneralHome` and `PlatformAdmin` may invoke any of these actions, whereas an `Operator` may invoke only `SET_STREAM_READY`, `SET_STREAM_FAILED`, `GO_LIVE`, and `END`; an action attempted by a role not permitted for it is rejected with `ERR_UNAUTHORIZED`. Before a service can be scheduled, an operator must ready the stream. Marking the stream ready advances `stream_status` to `READY` from either `PENDING` or `FAILED`; marking it failed advances `stream_status` to `FAILED` from either `PENDING` or `READY`. Any stream toggle attempted from a state that does not permit it is rejected with `ERR_STREAM_INVALID_STATE`.

Scheduling advances `broadcast_status` from `DRAFT` to `SCHEDULED` and is the system's most heavily guarded transition. It requires, in order, that the order be in `DRAFT` (otherwise `ERR_ORDER_NOT_DRAFT`), that at least one venue booking of the order be `CONFIRMED` (otherwise `ERR_VENUE_NOT_CONFIRMED`), that `stream_status` be `READY` (otherwise `ERR_STREAM_NOT_READY`), and that the home's `stream_credit_balance` be at least one (otherwise `ERR_INSUFFICIENT_STREAM_CREDITS`). On success the transition consumes one stream credit from the home and computes the forward estimate `estimated_cost_cents` from the scheduled duration, as described below.

Going live advances `broadcast_status` from `SCHEDULED` to `LIVE`; it requires the order to be `SCHEDULED` (otherwise `ERR_ORDER_NOT_SCHEDULED`) and `stream_status` to be `READY` (otherwise `ERR_STREAM_NOT_READY`), and it stamps `actual_start` with the current logical-clock instant. Ending the broadcast advances `broadcast_status` from `LIVE` to `ENDED`; it requires the order to be `LIVE` (otherwise `ERR_ORDER_NOT_LIVE`), stamps `actual_end` from the logical clock, moves `recording_status` from `NONE` to `RAW`, and sets `recording_duration_minutes` from the aired duration. While `actual_end` is still unset, `recording_duration_minutes` is zero; once both instants exist, it is the elapsed time from `actual_start` to `actual_end` in seconds, divided by sixty and rounded up to the next whole minute.

Cancellation is available while the order is in either `DRAFT` or `SCHEDULED`; attempting it from any other broadcast state is rejected with `ERR_ORDER_NOT_CANCELLABLE`. Cancelling advances `broadcast_status` to `CANCELLED`, sets `settlement_status` to `VOID`, and cascades every `HELD` or `CONFIRMED` venue booking of the order to `RELEASED` (which itself releases the order's `ASSIGNED` camera assignments per §2.8). When the order being cancelled was `SCHEDULED`, cancellation additionally refunds the one stream credit that scheduling consumed, adding one back to the home's `stream_credit_balance`; when it was still `DRAFT`, no credit had been consumed, so none is refunded. Both cancellation paths void settlement and run the booking cascade identically; they differ only in the credit refund.

**Service billing.** The stream fee is tiered. Start from the billable `duration_minutes`: for the forward estimate it is the scheduled window from `scheduled_start` to `scheduled_end` in seconds divided by sixty and rounded up to a whole minute; for the final invoice it is `recording_duration_minutes`, the actual aired duration. The included allowance is 120 minutes (two hours): the overage is the duration minus 120, floored at zero, so a duration of exactly 120 minutes yields no overage and billable overage begins only at 121 minutes. The first 60 overage minutes are billed at 100 cents per minute; every overage minute beyond that first 60 is billed at 150 cents per minute. To this the system adds a base fee of 15,000 cents plus 5,000 cents for each camera in `camera_count`, and, when `priority_support` is true, a flat priority-support surcharge of 10,000 cents (omitted when it is false). The estimate is computed at scheduling and stored in `estimated_cost_cents`; the final figure is computed at invoicing and stored in `final_invoice_cents`, and it diverges from the estimate whenever the broadcast ran longer or shorter than planned.

### 3.7. Settlement and Invoicing

Billing runs on its own axis, independent of the broadcast. Invoicing advances `settlement_status` from `UNBILLED` to `INVOICED`; it requires that the broadcast have `ENDED` (otherwise `ERR_ORDER_NOT_ENDED`) and that settlement still be `UNBILLED` (otherwise `ERR_ORDER_NOT_UNBILLED`), and it computes `final_invoice_cents` from the actual aired duration using the final variant of the service-billing rule in §3.6. Recording payment advances `settlement_status` from `INVOICED` to `PAID`; it requires that settlement be `INVOICED` (otherwise `ERR_ORDER_NOT_INVOICED`) and has no further side effects. As noted in §3.6, cancelling an order sets `settlement_status` directly to `VOID` regardless of the billing track.

### 3.8. Recording Production and Delivery

Ending a broadcast spawns a raw recording, putting `recording_status` at `RAW`. From there the funeral home drives a short production pipeline. Starting the edit advances `recording_status` from `RAW` to `EDITING`; marking the recording ready advances it from `EDITING` to `READY`; and delivering it advances it from `READY` to `DELIVERED`. Any of these attempted out of order is rejected with `ERR_RECORDING_INVALID_STATE`. Delivery additionally requires a destination: the `DELIVER_RECORDING` request may itself carry a `delivery_email`, which — when present and non-null — is written onto the order before the check; the `delivery_email` on the order must then be non-null, or the delivery is rejected with `ERR_DELIVERY_EMAIL_MISSING`.

### 3.9. The Memorial Page: Access, Guestbook, and Donations

Each service order carries a public memorial page that the funeral home publishes when it is ready to receive the community. Publishing the memorial advances `memorial_status` from `DRAFT` to `PUBLISHED`; archiving it later advances `memorial_status` from `PUBLISHED` to `ARCHIVED`. Either transition attempted from the wrong state is rejected with `ERR_MEMORIAL_INVALID_STATE`. Publication is the gate for guest participation: guests may post condolences and pledge donations only once the memorial page is `PUBLISHED`.

**Guest link access.** A guest reaches a private service by attempting its guest link with a `password`. On a correct password the attempt succeeds and the endpoint returns the service-order resource with HTTP 200. On a wrong password, provided the link is not already locked, the order's `failed_access_count` is incremented by one and the attempt is rejected with `ERR_INVALID_ACCESS_PASSWORD`. The link locks once `failed_access_count` reaches five failed attempts: `access_locked` becomes true at exactly the fifth wrong attempt (the threshold is met, not exceeded, at five) and the counter stops incrementing thereafter. Any further attempt once the link is locked is rejected with `ERR_ACCESS_LOCKED`.

**Guestbook.** A guest posts a condolence by supplying the `order_id`, an `author_name`, and a `message`; the entry is created in `PENDING` status, and creation requires the order's `memorial_status` to be `PUBLISHED`, otherwise it is rejected with `ERR_MEMORIAL_NOT_PUBLISHED`. The funeral home moderates entries by supplying a `decision`, which is either `APPROVE` or `HIDE` (any other value is rejected with `ERR_VALIDATION`). Approving a pending entry advances its `status` from `PENDING` to `APPROVED` and recomputes the order's `guestbook_entry_count`, which counts only `APPROVED` entries. Hiding an entry advances its `status` to `HIDDEN` from either `PENDING` or `APPROVED`; when the hidden entry had been `APPROVED`, the order's `guestbook_entry_count` is recomputed to reflect its removal, whereas hiding a still-`PENDING` entry leaves the count unchanged. Any moderation from an incompatible state is rejected with `ERR_GUESTBOOK_INVALID_STATE`. Entries may be listed with an optional `order_id` filter or fetched individually.

**Donations.** A guest pledges a donation by supplying the `order_id`, a `donor_name`, and a `gross_amount_cents` that must be greater than zero, otherwise `ERR_INVALID_DONATION_AMOUNT`; the donation requires a `PUBLISHED` memorial, otherwise `ERR_MEMORIAL_NOT_PUBLISHED`. The donation is created in `PLEDGED` status with `fee_cents` and `net_amount_cents` null until settlement populates them, copies the order's `home_id`, and the home's provisional `donations_pledged_cents` is recomputed. A `PlatformAdmin` settles or refunds donations by supplying an `action` of `SETTLE` or `REFUND` on the donation-transition endpoint (any other value is rejected with `ERR_VALIDATION`). Settling advances a donation's `status` from `PLEDGED` to `SETTLED` (otherwise `ERR_DONATION_NOT_PLEDGED`) and finalizes its ledger figures: the per-donation `fee_cents` is the gross amount multiplied by 2.9 percent, rounded half up to the nearest cent, plus a flat 30 cents, and `net_amount_cents` is the gross amount minus that fee. Settlement then recomputes the order's `donations_net_cents` (the sum of `net_amount_cents` over that order's `SETTLED` donations), and that recompute cascades to the home's `donations_net_cents` (the sum over the home's `SETTLED` donations). The home's `donations_pledged_cents` is the sum of `gross_amount_cents` over the home's donations that are either `PLEDGED` or `SETTLED`, while the net totals sum only `SETTLED` donations — so the pledged total and the net total diverge both by the fee and by the status filter.

Refunding advances a donation's `status` to `REFUNDED` from either `PLEDGED` or `SETTLED`; a refund from any other state is rejected with `ERR_DONATION_NOT_REFUNDABLE`. Refunding a donation that was still `PLEDGED` touches no net totals, because its net was never counted. Refunding a donation that had already `SETTLED` is a compensating adjustment: its `net_amount_cents` is removed from the order's `donations_net_cents`, and that recompute cascades to the home's `donations_net_cents`, so the settled totals stay conserved. Donations may be listed with optional `order_id` and `home_id` filters or fetched individually.

### 3.10. The Tribute Video Review Loop

A funeral home produces a **tribute video** or photo montage for a service by supplying the `order_id`, a `title`, and a `photo_count`; it opens in `DRAFT` with a `revision_count` of zero. The review loop alternates between the home and a platform reviewer, and each step is requested through the tribute-transition endpoint's `action` field, one of `SUBMIT`, `REQUEST_CHANGES`, `APPROVE`, or `PUBLISH` (any other value is rejected with `ERR_VALIDATION`); `SUBMIT` and `PUBLISH` may be invoked by the funeral home or a `PlatformAdmin`, while `REQUEST_CHANGES` and `APPROVE` are `PlatformAdmin`-only, and an action attempted by a role not permitted for it is rejected with `ERR_UNAUTHORIZED`. The home submits a draft, advancing `status` from `DRAFT` to `SUBMITTED`. A `PlatformAdmin` either requests changes, moving `status` from `SUBMITTED` to `CHANGES_REQUESTED`, or approves, moving `status` from `SUBMITTED` to `APPROVED`. When changes were requested, the home resubmits, moving `status` from `CHANGES_REQUESTED` back to `SUBMITTED` and incrementing `revision_count` by one — this back-edge is the revision loop, and it is the only transition that bumps the revision counter. Finally the home publishes an approved tribute, advancing `status` from `APPROVED` to `PUBLISHED`. Any tribute action attempted from a state that does not permit it is rejected with `ERR_TRIBUTE_INVALID_TRANSITION`. Tribute videos may be listed with an optional `order_id` filter or fetched individually.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return a `201 Created` status code. Operations that modify an existing resource — including state transitions, moderation decisions, credit grants, and duty toggles — return a `200 OK` status code. The logical-clock test-driving capability returns `200 OK` with a null data payload.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/funeral-homes` | Create a funeral-home (vendor) account | PlatformAdmin |
| GET | `/funeral-homes/{id}` | Get a funeral-home account | FuneralHome, PlatformAdmin |
| POST | `/funeral-homes/{id}/credit-grants` | Grant prepaid stream credits to a funeral home | PlatformAdmin |
| POST | `/venues` | Create a venue for a funeral home | FuneralHome, PlatformAdmin |
| GET | `/venues` | List venues (filter by `home_id`) | FuneralHome, PlatformAdmin |
| GET | `/venues/{id}` | Get a venue | FuneralHome, PlatformAdmin |
| POST | `/operators` | Create a tech / on-call operator | FuneralHome, PlatformAdmin |
| GET | `/operators` | List operators (filter by `home_id`) | FuneralHome, PlatformAdmin |
| GET | `/operators/{id}` | Get an operator | FuneralHome, PlatformAdmin |
| POST | `/operators/{id}/duty` | Set an operator on or off duty | Operator, FuneralHome, PlatformAdmin |
| POST | `/service-orders` | Create a funeral live-stream service order | FuneralHome, PlatformAdmin |
| GET | `/service-orders` | List service orders (filter by `home_id`, `venue_id`) | FuneralHome, PlatformAdmin |
| GET | `/service-orders/{id}` | Get a service order | FuneralHome, PlatformAdmin |
| POST | `/service-orders/{id}/transitions` | Drive a service-order axis transition | FuneralHome, Operator, PlatformAdmin |
| POST | `/service-orders/{id}/access` | Guest attempts the private guest link with a password | Guest |
| POST | `/venue-bookings` | Reserve a venue window for a service order | FuneralHome, PlatformAdmin |
| GET | `/venue-bookings` | List venue bookings (filter by `order_id`, `venue_id`, `home_id`) | FuneralHome, PlatformAdmin |
| GET | `/venue-bookings/{id}` | Get a venue booking | FuneralHome, PlatformAdmin |
| POST | `/venue-bookings/{id}/confirm` | Confirm a held venue booking | FuneralHome, PlatformAdmin |
| POST | `/camera-assignments` | Assign an operator to a service order's stream window | FuneralHome, PlatformAdmin |
| GET | `/camera-assignments` | List camera assignments (filter by `order_id`, `operator_id`, `home_id`) | FuneralHome, PlatformAdmin |
| GET | `/camera-assignments/{id}` | Get a camera assignment | FuneralHome, PlatformAdmin |
| POST | `/guestbook-entries` | Guest posts a condolence entry | Guest |
| GET | `/guestbook-entries` | List guestbook entries (filter by `order_id`) | FuneralHome, PlatformAdmin |
| GET | `/guestbook-entries/{id}` | Get a guestbook entry | FuneralHome, PlatformAdmin |
| POST | `/guestbook-entries/{id}/moderation` | Moderate a guestbook entry | FuneralHome, PlatformAdmin |
| POST | `/donations` | Guest pledges a donation | Guest |
| GET | `/donations` | List donations (filter by `order_id`, `home_id`) | FuneralHome, PlatformAdmin |
| GET | `/donations/{id}` | Get a donation | FuneralHome, PlatformAdmin |
| POST | `/donations/{id}/transitions` | Settle or refund a donation | PlatformAdmin |
| POST | `/tribute-videos` | Create a tribute video / photo montage | FuneralHome, PlatformAdmin |
| GET | `/tribute-videos` | List tribute videos (filter by `order_id`) | FuneralHome, PlatformAdmin |
| GET | `/tribute-videos/{id}` | Get a tribute video | FuneralHome, PlatformAdmin |
| POST | `/tribute-videos/{id}/transitions` | Drive the tribute review loop | FuneralHome, PlatformAdmin |
| POST | `/_clock/set_current_utc` | Set the server logical clock (test-driving) | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_CROSS_TENANT_FORBIDDEN` | 403 Forbidden |
| `ERR_FUNERAL_HOME_NOT_FOUND` | 404 Not Found |
| `ERR_VENUE_NOT_FOUND` | 404 Not Found |
| `ERR_OPERATOR_NOT_FOUND` | 404 Not Found |
| `ERR_SERVICE_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_VENUE_BOOKING_NOT_FOUND` | 404 Not Found |
| `ERR_CAMERA_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_GUESTBOOK_ENTRY_NOT_FOUND` | 404 Not Found |
| `ERR_DONATION_NOT_FOUND` | 404 Not Found |
| `ERR_TRIBUTE_VIDEO_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
| `ERR_INVALID_TIME_RANGE` | 422 Unprocessable Entity |
| `ERR_INVALID_CAMERA_COUNT` | 422 Unprocessable Entity |
| `ERR_INVALID_DONATION_AMOUNT` | 422 Unprocessable Entity |
| `ERR_ORDER_NOT_DRAFT` | 409 Conflict |
| `ERR_ORDER_NOT_SCHEDULED` | 409 Conflict |
| `ERR_ORDER_NOT_LIVE` | 409 Conflict |
| `ERR_ORDER_NOT_ENDED` | 409 Conflict |
| `ERR_ORDER_NOT_UNBILLED` | 409 Conflict |
| `ERR_ORDER_NOT_INVOICED` | 409 Conflict |
| `ERR_ORDER_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_BOOKING_NOT_HELD` | 409 Conflict |
| `ERR_STREAM_INVALID_STATE` | 409 Conflict |
| `ERR_RECORDING_INVALID_STATE` | 409 Conflict |
| `ERR_MEMORIAL_INVALID_STATE` | 409 Conflict |
| `ERR_DELIVERY_EMAIL_MISSING` | 409 Conflict |
| `ERR_DONATION_NOT_PLEDGED` | 409 Conflict |
| `ERR_DONATION_NOT_REFUNDABLE` | 409 Conflict |
| `ERR_GUESTBOOK_INVALID_STATE` | 409 Conflict |
| `ERR_TRIBUTE_INVALID_TRANSITION` | 409 Conflict |
| `ERR_ACCESS_LOCKED` | 409 Conflict |
| `ERR_VENUE_NOT_CONFIRMED` | 409 Conflict |
| `ERR_STREAM_NOT_READY` | 409 Conflict |
| `ERR_MEMORIAL_NOT_PUBLISHED` | 409 Conflict |
| `ERR_OPERATOR_OFF_DUTY` | 409 Conflict |
| `ERR_VENUE_TIME_CONFLICT` | 409 Conflict |
| `ERR_OPERATOR_TIME_CONFLICT` | 409 Conflict |
| `ERR_INVALID_ACCESS_PASSWORD` | 403 Forbidden |
| `ERR_INSUFFICIENT_STREAM_CREDITS` | 402 Payment Required |
| `ERR_STALE_ORDER_VERSION` | 412 Precondition Failed |

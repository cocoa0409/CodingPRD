# Out-of-Home Billboard Booking API — Product Requirements Document

## 1. Introduction

An out-of-home advertising operator in the style of Lamar or OUTFRONT manages a physical estate of billboard faces spread across designated market areas. Some faces are static vinyl structures; others are digital boards that sell shares of a fixed 64-second display loop. Every face is priced from a market rate card, gated by a jurisdiction-issued permit, subject to structure maintenance, and sold to advertisers through campaigns composed of individual date-bounded flights. Revenue is earned only when copy is actually posted and verified with photographic proof, and the operator owes make-good credit when it fails to deliver what was sold — a missed posting, an illumination outage, a permit suspension, or an audience shortfall against the guaranteed impressions estimate.

This document specifies an API that runs that entire book of business deterministically. Pricing is pinned at the moment a hold is placed and never re-rated retroactively; availability is exposed through two reconcilable calendars; posting verification is segregated from installation; and a logical clock with a fixed sweep order drives every time-based transition — permit aging, hold expiry, missed-posting marking, and end-of-flight resolution — so that the passage of time is reproducible rather than accidental. The intended readers are the engineers who will implement the service; every rule stated here is contractual.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope formats, and cross-cutting principles that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the capacity in which they act. A request missing either header, or carrying an unrecognized role value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. A request whose role is not permitted for the endpoint — or for the specific transition being requested on that endpoint — is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The system recognizes nine roles, spelled exactly as follows: `PlatformAdmin` (drives the logical clock), `InventoryManager` (owns faces and rate cards), `SalesPlanner` (builds advertisers, campaigns, flight holds, and confirms), `SalesManager` (approves, rejects, or cancels campaigns), `ProductionCoordinator` (runs the artwork pipeline), `FieldInstaller` (reports postings with photo proof), `OperationsAuditor` (verifies photo proof, proposes make-goods, appends impression entries, confirms takedowns), `ComplianceOfficer` (files permits and runs maintenance work orders), and `FinanceAnalyst` (manages credit, billing, and make-good settlement).

For every one of these roles — `PlatformAdmin`, `InventoryManager`, `SalesPlanner`, `SalesManager`, `ProductionCoordinator`, `FieldInstaller`, `OperationsAuditor`, `ComplianceOfficer`, and `FinanceAnalyst` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server never compares it against a resource's `id`. It may record the identifier for accountability: the `installer_user_id` captured on a posting record, the `verified_by_user_id` stamped at verification, and the `proposed_by` field on a make-good (which may also hold the literal value `system` for auto-proposed credits) are the places where an operator's `X-User-ID` becomes visible inside a resource.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits. It is read from the wall clock; the logical clock of §2.5 governs resource `created_at`/`updated_at` fields and every rule-driven timestamp, not this envelope field.
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

List endpoints accept the query parameters `limit` and `offset`. The `limit` parameter caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. A `limit` or `offset` value that does not parse as an integer is rejected with `ERR_INVALID_REQUEST`; out-of-range integers are clamped rather than rejected — `limit` into the 1–100 band and `offset` up to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by creation order. Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `total_count` counts the full filtered collection before paging and `has_more` is true exactly when items remain beyond the returned page. Certain list endpoints additionally accept an optional `status` query parameter that filters the returned collection to a single lifecycle state; where supported, this is noted alongside the workflow that owns the collection. A `status` filter value outside the resource's lifecycle matches nothing and simply yields an empty page.

### 2.4. Common Resource Properties

Every resource in the API — rate cards, faces, permits, maintenance work orders, advertiser accounts, campaigns, flights, artwork orders, posting records, and make-goods — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every recorded modification of the resource.
- `version` (integer): a system-managed integer that starts at 1 when the resource is created and increments with every recorded modification, including the explicit version bumps called out in the workflow narratives (rate-card updates and status transitions, face updates, flight creation against a face, and every campaign status or billing transition including the confirm that locks a flight's discount).

### 2.5. The Logical Clock and Deterministic Time

The server keeps a logical clock rather than reading the wall clock. At startup the clock reads exactly `2026-08-01T00:00:00Z`, and before any operator advances it, every time-dependent rule in this document evaluates against that default. A `PlatformAdmin` advances the clock through an administrator-only capability that accepts a `to_iso8601` instant; the target must be strictly later than the current reading, otherwise the call is rejected with `ERR_INVALID_REQUEST`. A successful advance returns the new reading as `current_utc` — rendered as an ISO 8601 UTC timestamp without fractional digits when the reading lands on a whole second, and with three fractional digits otherwise — and triggers the deterministic sweep.

Each sweep runs four steps in a fixed order, applying every cascade described in §3 before moving on:

1. **Permit aging** — permits approaching expiry move from `ACTIVE` to `RENEWAL_PENDING`; permits at or past expiry become `EXPIRED`, each triggering the face suspension cascade.
2. **Hold expiry** — held flights whose deadline has passed move from `HELD` to `EXPIRED`, freeing their reserved occupancy.
3. **Missed-posting marking** — booked or art-cleared flights that still lack a verified posting three days after their start move to `MISSED`.
4. **End-of-flight resolution** — live flights past their end date move to `HOLDOVER` or directly to `COMPLETED`, depending on successor postings.

Because the steps are ordered, a single clock advance can, for example, expire a permit and suspend its face before the same sweep marks that face's late flights as missed.

### 2.6. Money, Impressions, and Rounding Discipline

All monetary amounts are integer cents; no fractional cents exist anywhere in the system. Whenever a computation produces a fractional cent value, the result is rounded half-up to the nearest whole cent. Two rounding-order rules are contractual: weekly rates are rounded once per week and only then multiplied by the number of weeks, and campaign-level net totals are rounded per flight and then summed — never the other way around, because the alternative order produces different cents. Percentage fields are stored as plain number fractions: an `illumination_premium_pct` of 0.15 means a fifteen-percent uplift. Two non-monetary computations have their own precision: `downtime_hours` on a completed work order is expressed in hours rounded to 2 decimal places, and a flight's `delivery_ratio` is a number with 4 decimal places, rounded half-up.

### 2.7. Booking Posture and Derived Permit State

A face's sellability is exposed through two read-only derived fields, recomputed whenever the underlying state changes. The `booking_posture` field is `OPEN` when the face is `AVAILABLE`, `RESTRICTED` while it is `UNDER_MAINTENANCE`, and `BLOCKED` when it is `PERMIT_SUSPENDED` or `DECOMMISSIONED`. Only an `OPEN` face accepts new holds or confirmations. The `current_permit_id` field names the `id` of the permit currently in force — one in `ACTIVE` or `RENEWAL_PENDING` status — and is null when no such permit exists. The `PERMIT_SUSPENDED` status itself is system-set only: it is reached exclusively through the permit cascade of §3.2, and any client attempt to write it directly is rejected with `ERR_INVALID_STATE`.

### 2.8. Nested Resource Retrieval and Existence Checking

When an endpoint path contains resource identifiers, the system validates their existence strictly left-to-right and rejects the request at the first identifier that does not resolve, returning the not-found error that corresponds to that resource type: `ERR_RATE_CARD_NOT_FOUND`, `ERR_FACE_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, `ERR_ADVERTISER_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_FLIGHT_NOT_FOUND`, `ERR_ARTWORK_ORDER_NOT_FOUND`, `ERR_POSTING_RECORD_NOT_FOUND`, or `ERR_MAKE_GOOD_NOT_FOUND`. Resource identifiers carried in the request body rather than the path — such as `advertiser_id` on campaign creation, `face_id` on permit or work-order filing, `flight_id` on artwork-order, posting-record, or make-good creation, and `campaign_id`, `face_id`, `rate_card_id`, and `predecessor_flight_id` on flight creation — are validated the same way, with the same typed not-found errors, in the order the workflow narrative names them, immediately after path identifiers resolve. Existence is established before any body-shape, state, or business rule is evaluated, so a request aimed at a nonexistent parent never surfaces a validation error about its payload.

### 2.9. The Validation Pipeline and Check Ordering

Every request is evaluated against a fixed pipeline of check families. A failure in an earlier family is reported immediately and masks every later family — a client never sees a business-rule rejection for a request whose body was malformed, and never sees a body-shape error for a resource that does not exist. The families, in evaluation order, are:

1. **Header presence** — `X-User-ID` and `X-User-Role` are present and the role is recognized (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. **Role authorization** — the role may use this endpoint and this specific transition (`ERR_INSUFFICIENT_PERMISSIONS`).
3. **Path existence** — identifiers resolve left-to-right (the `ERR_*_NOT_FOUND` family).
4. **Request shape** — required fields present, enum members valid, date and datetime strings parse, an end is never before its start, numeric ranges hold, the digital loop-slot rules hold, and artwork dimensions and material match the face (`ERR_INVALID_REQUEST`, `ERR_DIGITAL_SLOTS_REQUIRED`, `ERR_ARTWORK_DIMENSION_MISMATCH`, `ERR_MATERIAL_FACE_MISMATCH`).
5. **State legality and version freshness** — the target resource is in a state that allows the requested transition, terminal resources reject all mutations, and every optimistic-concurrency field matches the parent's current `version` (`ERR_INVALID_STATE`, `ERR_STALE_VERSION`).
6. **Segregation of duties** — verifier versus installer, approver versus proposer (`ERR_SEGREGATION_OF_DUTIES`).
7. **Face bookability** — the face's `booking_posture` is `OPEN` and a current permit exists (`ERR_FACE_NOT_BOOKABLE`).
8. **Related-entity status** — the campaign is in the required state for the operation, the rate card is published, the advertiser is active, a named predecessor flight qualifies, the campaign window contains the flight dates, and a posting target is postable (`ERR_CAMPAIGN_NOT_APPROVED`, `ERR_RATE_CARD_NOT_PUBLISHED`, `ERR_ADVERTISER_NOT_BOOKABLE`, `ERR_INVALID_REQUEST`, `ERR_FLIGHT_NOT_POSTABLE`).
9. **Clock-relative temporal rules** — the posting date window, permit expiry against the clock, and the hold confirmation deadline (`ERR_INVALID_REQUEST`).
10. **Static-face overlap and changeover** — (`ERR_FACE_OVERLAP`).
11. **Digital loop capacity** — (`ERR_LOOP_CAPACITY_EXCEEDED`).
12. **Uniqueness** — face-code uniqueness, one published rate card per market and display type, one non-terminal artwork order per flight, one verified posting per flight, and permit supersession shape (`ERR_INVALID_REQUEST`, `ERR_RATE_CARD_DUPLICATE_PUBLISHED`, `ERR_ACTIVE_ARTWORK_ORDER_EXISTS`, `ERR_INVALID_STATE`).
13. **Maintenance window exclusion** — (`ERR_MAINTENANCE_WINDOW_CONFLICT`).
14. **Credit** — exposure ceilings at confirm, credit-limit reductions, and the settlement gate (`ERR_CREDIT_LIMIT_EXCEEDED`, `ERR_UNRESOLVED_MAKE_GOODS`).

The ordering is observable. On flight creation, a bookability failure (`ERR_FACE_NOT_BOOKABLE`, family 7) is reported before a campaign-state failure (`ERR_CAMPAIGN_NOT_APPROVED`, family 8), and an overlap failure (family 10) is reported before a loop-capacity failure (family 11). At confirm, a stale campaign version (`ERR_STALE_VERSION`, family 5) surfaces before the credit check (family 14) ever runs. At posting verification, a second-verification attempt fails on state (family 5) before segregation of duties (family 6) is even consulted. Regarding terminal states: a resource in a terminal state rejects every further mutation with `ERR_INVALID_STATE`, except where a state machine explicitly defines an exit — the work-order reopen cycle from `COMPLETED` to `REOPENED` is the sole such exception in the system. Two write-shape rules cut across every state machine. A `status` value naming no transition the machine defines from the resource's current state is rejected with `ERR_INVALID_STATE` whatever the caller's role — per-transition role gates apply only to transitions the machine defines. And writing a `status` identical to the resource's current state is treated as no transition at all on rate cards, faces, advertisers, and campaigns — the request succeeds, applies any other field updates, and records a modification — while permits, work orders, flights, artwork orders, posting records, and make-goods accept only defined transitions and reject a same-state write with `ERR_INVALID_STATE`.

### 2.10. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, each keyed to the `version` of a parent entity the client must have read:

- **Creating a flight** (`POST /api/flights`) requires a non-optional `expected_face_version` field carrying the client's last observed `version` of the target face. The face version encodes the traffic count, illumination flag, and loop configuration the quote was priced from; if the face's current `version` differs, the creation is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the face and re-price.
- **Confirming a held flight** (`POST /api/flights/{id}/confirm`) requires a non-optional `expected_campaign_version` field carrying the client's last observed `version` of the flight's campaign. The campaign version encodes the contracted total from which the volume-discount tier is derived; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the campaign.
- **Updating a rate card** (`PUT /api/rate-cards/{id}`) requires a non-optional `expected_rate_card_version` field carrying the client's last observed `version` of the card. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), so that no intervening repricing is silently discarded.

Endpoints not listed here do not accept a version field at all.

### 2.11. Segregation of Duties

Two operations enforce a four-eyes principle. A posting record may only be verified or rejected by an `OperationsAuditor` whose `X-User-ID` differs from the record's `installer_user_id` — an installer can never audit their own work. A make-good whose `proposed_by` holds a user id may only be approved by a `FinanceAnalyst` whose `X-User-ID` differs from that proposer; make-goods whose `proposed_by` is the literal `system` may be approved by any `FinanceAnalyst`. Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES`.

## 3. Business Logic & Workflows

### 3.1. Building the Inventory: Rate Cards and Faces

An `InventoryManager` begins by drafting rate cards. A card is created with its `market_code` (the designated market area it prices, such as NYC), a `display_type` of either `STATIC` or `DIGITAL`, a `base_weekly_cents` rate before uplifts, an `illumination_premium_pct` uplift applied when a face is lit at night, and two traffic tiers: `traffic_tier_1_threshold` with `traffic_tier_1_uplift_pct`, and `traffic_tier_2_threshold` with `traffic_tier_2_uplift_pct`. The monetary and threshold fields must be non-negative integers and the percentage fields non-negative numbers, on update as on creation; a violation is `ERR_INVALID_REQUEST`. A new card is born in `DRAFT`.

Publishing a card (the `DRAFT` → `PUBLISHED` transition) enforces two checks: the tier-2 threshold must be strictly greater than the tier-1 threshold, otherwise `ERR_INVALID_REQUEST`; and no other card for the same `market_code` and `display_type` pair may already be `PUBLISHED`, otherwise `ERR_RATE_CARD_DUPLICATE_PUBLISHED`. A card may be retired from either `DRAFT` or `PUBLISHED` into the terminal `RETIRED` state. Retirement is never retroactive: flights already created against the card keep their `pinned_weekly_cents` and `pinned_rate_card_version` exactly as pinned. Every update to a card — rates or status — increments its `version` by 1 and passes through the optimistic-concurrency guard of §2.10. A card's booking history is readable as the list of flights that pinned it.

Faces are the sellable units. Registering a face takes a globally unique `face_code` (a duplicate is rejected with `ERR_INVALID_REQUEST`), an informational `structure_code` grouping the physical structure, the `market_code`, the `display_type`, the `illuminated` flag, the `daily_traffic_count` that serves as the impressions basis, and the copy dimensions `width_inches` and `height_inches`; the traffic count must be a non-negative integer and each dimension an integer of at least 1. A `DIGITAL` face additionally requires `loop_slots_total` — the number of advertising slots in its 64-second loop, between 1 and 16 inclusive — while a `STATIC` face must omit `loop_slots_total` entirely; either violation is rejected with `ERR_DIGITAL_SLOTS_REQUIRED`. A new face is born `AVAILABLE` with `booking_posture` `OPEN` and a null `current_permit_id`.

Updating a face's `daily_traffic_count` or `illuminated` flag increments the face's `version` and recomputes `estimated_impressions` for every flight on that face still in `HELD`, `BOOKED`, or `ART_CLEARED` (the formula lives in §3.8). An `InventoryManager` may also move a face manually between `AVAILABLE` and `UNDER_MAINTENANCE`, and may decommission a face — but only when no flight on it sits in `HELD`, `BOOKED`, `ART_CLEARED`, `LIVE`, `MISSED`, or `HOLDOVER`, otherwise the request fails with `ERR_INVALID_STATE`. Decommissioning a face that is currently `UNDER_MAINTENANCE` additionally cancels every work order on that face still in `OPEN` or `SCHEDULED`. Both decommission paths land on the terminal `DECOMMISSIONED` state with `booking_posture` `BLOCKED`.

### 3.2. Permits, Renewals, and the Suspension Cascade

Every sellable face must hold a permit from its jurisdiction. A `ComplianceOfficer` files a permit with the `face_id`, the jurisdiction-issued `permit_number`, the issuing `jurisdiction`, an `issued_on` timestamp, and an `expires_on` timestamp that must be strictly after `issued_on` and strictly later than the current clock reading — an inverted or already-past expiry is `ERR_INVALID_REQUEST`. A permit is valid strictly until `expires_on`. A filed permit is born `ACTIVE` and becomes the face's `current_permit_id`.

Renewals form a chain. When the filing carries a `supersedes_permit_id`, the referenced permit must currently be `ACTIVE` or `RENEWAL_PENDING`; filing succeeds by moving that predecessor to `SUPERSEDED` and pointing the face's `current_permit_id` at the new permit. When no `supersedes_permit_id` is given, the face must have no current permit at all — filing against a face that already has an un-superseded current permit is rejected with `ERR_INVALID_STATE`. At filing, these supersession-shape checks run before the expiry-against-the-clock rule, so a supersession violation surfaces `ERR_INVALID_STATE` even when the proposed `expires_on` is already past. A permit's renewal chain is inspectable through the successor inquiry, which lists the permits whose `supersedes_permit_id` points at a given permit.

Time alone changes permits. When the clock stands anywhere from thirty days before `expires_on` up to but not including `expires_on`, the sweep moves an `ACTIVE` permit to `RENEWAL_PENDING`. Once the clock reaches `expires_on`, a permit in `ACTIVE` or `RENEWAL_PENDING` becomes `EXPIRED` — and the cascade begins: the face's `current_permit_id` is cleared to null, the face moves from `AVAILABLE` or `UNDER_MAINTENANCE` to `PERMIT_SUSPENDED` with `booking_posture` recomputed to `BLOCKED`, every flight on that face in `LIVE` or `HOLDOVER` has its `suspension_started_at` stamped with the current clock reading, and each affected flight's campaign has its `delivery_posture` recomputed.

A `ComplianceOfficer` may also revoke a permit, moving it to the terminal `REVOKED` state from `ACTIVE`, `RENEWAL_PENDING`, or `EXPIRED`. Revoking an `ACTIVE` or `RENEWAL_PENDING` permit clears `current_permit_id` and drives the same suspension cascade as expiry; revoking an already-`EXPIRED` permit leaves the face in `PERMIT_SUSPENDED`, since it is already suspended.

Restoration runs the cascade in reverse. Reinstating a permit (the `EXPIRED` → `ACTIVE` transition) requires a new `expires_on` strictly later than the current clock reading, otherwise `ERR_INVALID_REQUEST`. Whenever a permit on a suspended face becomes `ACTIVE` — by reinstatement or by a new filing, including a superseding renewal — the face's `current_permit_id` is set, and the face leaves `PERMIT_SUSPENDED`: it returns to `AVAILABLE` (posture `OPEN`), or to `UNDER_MAINTENANCE` (posture `RESTRICTED`) when a work order on the face is currently `IN_PROGRESS`. For each flight carrying a set `suspension_started_at`, the number of days between that stamp and the restoration moment is added to `suspension_days_accrued`, the stamp is cleared to null, and a make-good with reason `PERMIT_SUSPENSION` is auto-created in `PROPOSED` status with `proposed_by` set to the literal `system`, its credit computed per §3.9. Each affected campaign's `delivery_posture` is then recomputed.

### 3.3. Structure Maintenance and Work Orders

A `ComplianceOfficer` opens a maintenance work order against a face with the `face_id`, an `order_type` of `ILLUMINATION_OUTAGE`, `STRUCTURAL_REPAIR`, `VEGETATION_CLEARANCE`, or `POSTING_DAMAGE`, and an optional free-text `description` that defaults to empty. A new order is born `OPEN`.

Scheduling an order (the `OPEN` → `SCHEDULED` transition) supplies `scheduled_start` and `scheduled_end`. The end must be strictly after the start, otherwise `ERR_INVALID_REQUEST`. The planned window is half-open — it covers the calendar dates from the date of `scheduled_start` through the date one second before `scheduled_end` — and it must not touch any date occupied by a flight on the same face in `BOOKED`, `ART_CLEARED`, `LIVE`, `MISSED`, or `HOLDOVER`; a touch is rejected with `ERR_MAINTENANCE_WINDOW_CONFLICT`. One exemption exists: an `ILLUMINATION_OUTAGE` order is a reactive outage report rather than a planned booking, so it schedules without the window check.

Starting work (the `SCHEDULED` → `IN_PROGRESS` transition) stamps `started_at` with the clock and moves the face from `AVAILABLE` to `UNDER_MAINTENANCE`, recomputing its posture to `RESTRICTED`. Completing work stamps `completed_at`, computes `downtime_hours` as the elapsed hours between `started_at` and `completed_at` rounded to 2 decimal places, and returns the face from `UNDER_MAINTENANCE` to `AVAILABLE` — but only when zero sibling work orders on that face remain `IN_PROGRESS`. Completion carries a revenue side effect for lit faces: when an `ILLUMINATION_OUTAGE` order completes on an `illuminated` face, every flight on that face in `LIVE`, `MISSED`, or `HOLDOVER` whose booked dates intersect the outage span (the calendar dates from `started_at` through `completed_at`) receives an auto-created make-good with reason `ILLUMINATION_OUTAGE`, status `PROPOSED`, and `proposed_by` set to `system`.

Completed is not quite final. Reopening (the `COMPLETED` → `REOPENED` transition) increments `reopen_count` by 1 — this cycle counter is the only exception to the terminal-state lockdown noted in §2.9. Driving a reopened order back to `IN_PROGRESS` re-stamps `started_at`, clears `completed_at` and `downtime_hours` to null, and puts the face back into `UNDER_MAINTENANCE`. An order may instead be cancelled from `OPEN` or `SCHEDULED` into `CANCELLED`. The work-order collection of a face can be listed with an optional `status` filter.

### 3.4. Advertisers, Credit, and the Campaign Lifecycle

A `SalesPlanner` onboards an advertiser account with a legal `name` and a `credit_limit_cents` ceiling. The account is born `ACTIVE` with `credit_balance_cents` at 0 and `exposure_cents` at 0. Exposure is a computed ledger: it sums `net_cents` across the advertiser's flights in `BOOKED`, `ART_CLEARED`, `LIVE`, `MISSED`, or `HOLDOVER`, and adds those flights' `holdover_charge_cents` on top. The credit rule is a strict ceiling with an inclusive boundary — exposure exactly equal to `credit_limit_cents` is allowed; exposure above it is not.

A `FinanceAnalyst` steers the account's credit posture: `ACTIVE` ↔ `CREDIT_HOLD` in either direction, `ACTIVE` or `CREDIT_HOLD` into `SUSPENDED`, and `SUSPENDED` back to `ACTIVE`. The same update path changes `credit_limit_cents`, but lowering the limit below the account's current exposure is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`. An advertiser in `CREDIT_HOLD` or `SUSPENDED` is not bookable: campaign approval and flight confirmation both fail with `ERR_ADVERTISER_NOT_BOOKABLE` while the hold stands.

Campaigns organize flights under an advertiser. A `SalesPlanner` creates one with the `advertiser_id`, a `name`, and a `start_date`/`end_date` window (inclusive dates; the end must not precede the start, otherwise `ERR_INVALID_REQUEST`). Every flight of the campaign must lie inside that window — a hold whose dates fall outside is rejected with `ERR_INVALID_REQUEST`. A new campaign is born `DRAFT` with `billing_status` `UNINVOICED` and `delivery_posture` `ON_TRACK`.

The approval chain is segregated by role. Submitting (the `DRAFT` → `SUBMITTED` transition, by a `SalesPlanner`) requires at least one flight of the campaign to be sitting in `HELD`, otherwise `ERR_CAMPAIGN_EMPTY`. Approving (`SUBMITTED` → `APPROVED`, by a `SalesManager`) requires the advertiser to be `ACTIVE`, otherwise `ERR_ADVERTISER_NOT_BOOKABLE`. A `SalesManager` may instead push the campaign back from `SUBMITTED` to `DRAFT` for revision. Activation is automatic: the campaign moves `APPROVED` → `ACTIVE` the moment its first flight enters `LIVE`. Completion is likewise automatic: once every flight of the campaign has reached `COMPLETED`, `CANCELLED`, `EXPIRED`, or `RELEASED`, the campaign moves `ACTIVE` → `COMPLETED`, and at that moment each `COMPLETED` flight is evaluated for an under-delivery make-good per §3.9. Every one of these transitions increments the campaign's `version` by 1.

Cancellation depends on where the campaign stands. Cancelling an `APPROVED` campaign (a `SalesManager` action) releases every `HELD` flight into `RELEASED`, cancels every flight in `BOOKED` or `ART_CLEARED` with the tiered cancellation fee of §3.5, and leaves flights in `LIVE`, `MISSED`, or `HOLDOVER` untouched to run their course. Cancelling a `DRAFT` campaign (a `SalesPlanner` action) is permitted only when every flight is in `HELD`, `EXPIRED`, or `RELEASED` — any flight at `BOOKED` or beyond fails with `ERR_INVALID_STATE` — and releases the `HELD` flights.

Billing runs on a parallel dimension, `billing_status`, independent of `status`. A `FinanceAnalyst` moves `UNINVOICED` → `INVOICED` only while the campaign's `status` is `ACTIVE` or `COMPLETED`, otherwise `ERR_INVALID_STATE`, and moves `INVOICED` → `SETTLED` only when zero make-goods across all of the campaign's flights remain in `PROPOSED` or `APPROVED`, otherwise `ERR_UNRESOLVED_MAKE_GOODS`. Billing transitions increment the campaign's `version` like any other. A single update request may carry both `status` and `billing_status`, in which case the status transition is applied first and the billing transition second; an update carrying neither is rejected with `ERR_INVALID_REQUEST`.

Four computed ledgers ride on the campaign. The `contracted_cents` ledger sums `gross_cents` plus `holdover_charge_cents` over flights in `BOOKED`, `ART_CLEARED`, `LIVE`, `MISSED`, `HOLDOVER`, and `COMPLETED`; flights in `HELD`, `EXPIRED`, `RELEASED`, or `CANCELLED` never count, and cancellation fees never count. Fees accumulate instead in `cancellation_fees_cents`, tracked separately. Artwork surcharges accumulate in `production_charges_cents` (see §3.6). The `discount_pct` records the volume tier locked by the most recent confirm, and `net_contracted_cents` sums the per-flight net amounts defined in §3.5. Finally, `delivery_posture` compounds delivery health: it is `UNDER_DELIVERED` when any `COMPLETED` flight has a `delivery_ratio` below 0.9; otherwise `AT_RISK` when any flight sits in `MISSED` or `HOLDOVER`, has `suspension_started_at` set, or carries `suspension_days_accrued` above zero; otherwise `ON_TRACK`.

### 3.5. Holding and Confirming Flights: Pricing, Availability, and Discounts

A `SalesPlanner` places inventory on hold by creating a flight. The payload names the `campaign_id`, the `face_id`, the `rate_card_id` to price from, the inclusive `start_date` and `end_date` (the end must not precede the start), and — for a digital face — the `loop_slots` the advertiser will occupy; an optional `predecessor_flight_id` chains a renewal, and the optimistic-concurrency field `expected_face_version` completes the request per §2.10. The campaign must be in `DRAFT` or `SUBMITTED` (otherwise `ERR_CAMPAIGN_NOT_APPROVED`), the rate card must be `PUBLISHED` (otherwise `ERR_RATE_CARD_NOT_PUBLISHED`), the face must stand at `booking_posture` `OPEN` with a current permit in force (otherwise `ERR_FACE_NOT_BOOKABLE`), and the flight's dates must lie inside the campaign window. A `DIGITAL` face requires `loop_slots` between 1 and its `loop_slots_total` inclusive; a `STATIC` face forbids the field — violations are `ERR_DIGITAL_SLOTS_REQUIRED`.

A new flight is born `HELD`, with `held_until` set exactly 72 hours after `created_at`. The hold immediately reserves occupancy on the face's forward calendar and increments the face's `version` by 1, since the occupancy basis has changed. If the clock reaches `held_until` before confirmation, the sweep moves the flight `HELD` → `EXPIRED` and frees the reserved occupancy exactly; a planner may likewise abandon a hold voluntarily (the `HELD` → `RELEASED` transition), freeing the same occupancy.

Pricing is pinned at creation and never moves again. The billed length `weeks` is the inclusive day count of the flight divided by seven and rounded up — a partial week bills as a full week. The weekly price starts from the card's `base_weekly_cents`, applies the traffic multiplier — the tier-2 uplift `traffic_tier_2_uplift_pct` when the face's `daily_traffic_count` is at least `traffic_tier_2_threshold`, otherwise the tier-1 uplift `traffic_tier_1_uplift_pct` when it is at least `traffic_tier_1_threshold`, otherwise no uplift — then applies the illumination premium (one plus `illumination_premium_pct`) when the face is `illuminated`, and finally, for a `DIGITAL` face, the slot share (`loop_slots` divided by `loop_slots_total`). The result is rounded half-up to whole cents, once, yielding `pinned_weekly_cents`; multiplying by `weeks` yields `gross_cents`. The card's identity and its observed `version` are captured in `rate_card_id` and `pinned_rate_card_version`, so later repricing or retirement of the card never disturbs the flight. While `HELD`, the flight's `discount_pct` is 0 and its `net_cents` is provisional, equal to `gross_cents`.

Two availability disciplines guard the hold. On a `STATIC` face, the new window must leave one full changeover day against every blocking interval — blocking intervals are the inclusive date ranges of flights in `BOOKED`, `ART_CLEARED`, `LIVE`, `MISSED`, or `HOLDOVER`, plus unexpired `HELD` holds — meaning the new flight either starts at least two days after an occupied interval's last day or ends at least two days before an occupied interval's first day. A `DIGITAL` face allows next-day adjacency: starting the day after an existing booking ends is fine. Any breach is `ERR_FACE_OVERLAP`. On a `DIGITAL` face, capacity is also enforced: summing `loop_slots` over the blocking flights whose windows intersect the new window and adding the new `loop_slots` must not exceed `loop_slots_total` — a sum exactly equal to the total is allowed, and only an excess is rejected with `ERR_LOOP_CAPACITY_EXCEEDED`. Expired holds never block.

Renewal chains deserve a note of their own. When `predecessor_flight_id` is supplied, the predecessor must currently be `LIVE` or `HOLDOVER`, and the new flight's `start_date` must fall exactly one day after the predecessor's `end_date` on a `DIGITAL` face, or exactly two days after on a `STATIC` face — the changeover day. Any other adjacency is rejected with `ERR_INVALID_REQUEST`. A flight's renewal lineage is inspectable through its successor-flights list.

Planners and inventory managers read the face's book through the availability inquiry, which requires `from_date` and `to_date` query parameters — a missing or unparsable date, or a `to_date` that precedes `from_date`, is `ERR_INVALID_REQUEST` — and answers with two calendars clipped to that window: `committed_calendar`, the merged union of occupied intervals over `BOOKED`, `ART_CLEARED`, `LIVE`, `MISSED`, and `HOLDOVER` flights, and `forward_calendar`, the same union with unexpired `HELD` holds added. Each calendar is a list of inclusive `start_date`/`end_date` interval pairs; intervals that touch with no free day between them merge, while intervals separated by exactly one free day stay split. The two calendars differ precisely on the windows covered only by unexpired holds.

Confirming a held flight (the `HELD` → `BOOKED` transition) is the moment money locks. The confirm requires the clock not yet to have reached `held_until` — a lapsed hold is swept to `EXPIRED` first; the campaign in `APPROVED` or `ACTIVE` (otherwise `ERR_CAMPAIGN_NOT_APPROVED`); the advertiser `ACTIVE` (otherwise `ERR_ADVERTISER_NOT_BOOKABLE`); the face still at `booking_posture` `OPEN` (otherwise `ERR_FACE_NOT_BOOKABLE`); the overlap and loop-capacity checks re-run against current occupancy, excluding the flight being confirmed itself, (`ERR_FACE_OVERLAP`, `ERR_LOOP_CAPACITY_EXCEEDED`); and the credit ceiling — the account's `exposure_cents` plus this flight's `net_cents` must stay at or below `credit_limit_cents`, equality permitted, otherwise `ERR_CREDIT_LIMIT_EXCEEDED`. The `expected_campaign_version` guard of §2.10 applies as well.

Confirmation also locks the volume discount, in a pinned evaluation order that breaks the apparent circle between tier and totals. First, the flight's `gross_cents` is already pinned from creation. Second, the prospective contracted total is computed as the campaign's current `contracted_cents` plus this flight's `gross_cents`. Third, the tier is read off that total: 0.10 — ten percent — when the prospective total is at least 15,000,000 cents (a $150,000 book); otherwise 0.05 — five percent — when it is at least 5,000,000 cents ($50,000); otherwise no discount. Fourth, this flight's `discount_pct` locks to that tier, immutably. Fifth, this flight's `net_cents` finalizes as `gross_cents` plus `holdover_charge_cents`, reduced by the locked discount, rounded half-up to whole cents — holdover charges are zero at confirm time, but the same per-flight formula applies to them when they accrue. Sixth, the campaign's `contracted_cents` becomes the prospective total, its `discount_pct` becomes this latest tier, and its `net_contracted_cents` is the sum of the per-flight net amounts, each rounded per flight before summing. Because rounding is per-flight and the tier depends on the running total, confirm order is observable: the same set of flights confirmed in a different order can lock different per-flight tiers. A successful confirm also increments the campaign's `version` by 1 and recomputes the advertiser's `exposure_cents`.

Cancelling a flight out of `BOOKED` or `ART_CLEARED` (a `SalesPlanner` action) charges a tiered fee on the days between the clock's current date and the flight's `start_date`: at least 28 days out, the fee is ten percent of `gross_cents`; from 14 to 27 days out, twenty-five percent; under 14 days, fifty percent. The fee is recorded on the flight as `cancellation_fee_cents` and accumulated into the campaign's `cancellation_fees_cents` — never into `contracted_cents` — while contracted, net, and exposure ledgers recompute and the face's occupancy is freed. The identical schedule and the identical recomputes apply whether the cancelled flight was `BOOKED` or `ART_CLEARED`. Cancelling from `MISSED` is different in kind: no fee is charged, `missed_days` is set to the full booked length (`weeks` times seven), and a full-flight make-good is auto-proposed with reason `MISSED_POSTING` and credit equal to the entire `gross_cents`, since the copy never ran at all.

### 3.6. Artwork Production and Posting Verification

Once a flight is `BOOKED`, a `ProductionCoordinator` submits an artwork order with the `flight_id`, a `creative_code`, the `material`, and the copy dimensions `width_inches` and `height_inches`. The flight must be `BOOKED` — submitting against any other flight state is `ERR_INVALID_STATE` — and at most one non-terminal artwork order may exist per flight, otherwise `ERR_ACTIVE_ARTWORK_ORDER_EXISTS`. The dimensions must equal the face's `width_inches` and `height_inches` exactly, otherwise `ERR_ARTWORK_DIMENSION_MISMATCH`. Material must suit the display type: a `DIGITAL` face requires `DIGITAL_FILE`, while a `STATIC` face requires `VINYL` or `POLYETHYLENE`; a mismatch is `ERR_MATERIAL_FACE_MISMATCH`. A new order is born `SUBMITTED` with `revision_count` at 0.

Production flows `SUBMITTED` → `IN_PRODUCTION` → `PRINTED` → `SHIPPED` → `DELIVERED`. From `IN_PRODUCTION`, the coordinator may send the order into `REVISION_REQUESTED`, which increments `revision_count` by 1, and a revised order loops back from `REVISION_REQUESTED` to `SUBMITTED` to run the pipeline again. Cancellation into `CANCELLED` is allowed from `SUBMITTED`, `IN_PRODUCTION`, or `REVISION_REQUESTED`.

Delivery closes the loop. At the `SHIPPED` → `DELIVERED` transition, the order's `production_charge_cents` is set to the excess of `revision_count` over two — zero when two or fewer revisions occurred — multiplied by 35,000 cents ($350 per revision beyond the second, two being free), and that amount is posted onto the campaign's `production_charges_cents` accumulator. The transition records two modifications on the order — the status change and the charge stamping — so its `version` advances by 2. The flight moves `BOOKED` → `ART_CLEARED`; when the flight has already advanced to `MISSED` or beyond, that flight transition is a no-op. The campaign's `delivery_posture` is recomputed.

With art cleared, a `FieldInstaller` reports the physical posting with the `flight_id`, the actual `posted_on` date, a `photo_proof_url` pointing at time-stamped photographic proof, and optional `notes` defaulting to empty. The flight must be `ART_CLEARED` or `MISSED`, otherwise `ERR_FLIGHT_NOT_POSTABLE`, and `posted_on` must fall no earlier than seven days before the flight's `start_date` and no later than the clock's current date, otherwise `ERR_INVALID_REQUEST`. The record is born `REPORTED`, and the server stamps `installer_user_id` from the reporter's `X-User-ID`.

An `OperationsAuditor` then judges the proof. Verification enforces segregation of duties — the verifier's `X-User-ID` must differ from `installer_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES` — and at most one record per flight may ever reach `VERIFIED`; a second verification is `ERR_INVALID_STATE`. Verification also requires the flight to be sitting in `ART_CLEARED` or `MISSED`; against any other flight state it fails with `ERR_INVALID_STATE`. On verification, `verified_by_user_id` is stamped with the verifier's identity, and timing decides what the flight does next. When `posted_on` is no later than two days after `start_date`, the flight moves to `LIVE` on time — from `ART_CLEARED`, or from `MISSED` when the sweep has already marked it, in which case no missed-posting make-good is proposed and `missed_days` stays 0. When `posted_on` is later than two days after `start_date`, the flight moves `MISSED` → `LIVE` as a late posting: `missed_days` is set to the days elapsed from `start_date` to `posted_on`, and a make-good with reason `MISSED_POSTING` is auto-created in `PROPOSED` with `proposed_by` set to `system` and credit per §3.9. Verification also cascades to successors: every other flight on the same face sitting in `LIVE` or `HOLDOVER` whose `end_date` is before the clock's current date moves to `COMPLETED`, processed in ascending `end_date` order with ties broken by ascending `created_at`, each computing its holdover charges per §3.7. If this flight is its campaign's first to reach `LIVE`, the campaign moves `APPROVED` → `ACTIVE`; affected delivery postures recompute.

Rejection is the auditor's other hand. It carries the same segregation-of-duties check, requires a non-empty `rejection_reason` (otherwise `ERR_INVALID_REQUEST`), and leaves the flight exactly where it stood — `ART_CLEARED` or `MISSED` — so the installer must submit a fresh posting record; a `REJECTED` record itself is terminal.

### 3.7. Live Delivery, Holdover, and Flight Completion

The clock sweep watches live inventory. A flight in `BOOKED` or `ART_CLEARED` that still has no `VERIFIED` posting when the clock reaches a point three days after its `start_date` is marked `MISSED`, and its campaign's `delivery_posture` tips to `AT_RISK`.

At the other end of the window, once the clock reaches the day after `end_date`, a `LIVE` flight resolves in one of two directions. For this rule, a successor is any other flight on the same face that holds a `VERIFIED` posting record, whether or not it chains through `predecessor_flight_id`. When no successor flight on the face holds a verified posting, the flight slips into `HOLDOVER` — the copy is still up beyond its paid window — and the campaign posture recomputes to `AT_RISK`. When a successor's posting is already verified, the flight moves `LIVE` → `COMPLETED` directly, with `holdover_weeks` 0 and `holdover_charge_cents` 0; the same direct completion also fires as a cascade when a successor's posting is verified while this flight's `end_date` is already behind the clock's current date. Either way, completion recomputes the campaign's posture and the advertiser's exposure, and evaluates the under-delivery make-good of §3.9.

A `HOLDOVER` flight completes in two ways: manual takedown confirmation by an `OperationsAuditor`, which requires `takedown_confirmed` to be true and is rejected with `ERR_INVALID_REQUEST` otherwise, or the same successor-verification cascade. Completion prices the overstay: holdover days run from the day after `end_date` through the clock's current date, `holdover_weeks` is that day count divided by seven and rounded up, and `holdover_charge_cents` is the number of holdover weeks multiplied by the premium weekly rate — `pinned_weekly_cents` increased by ten percent (a multiplier of 1.10), rounded half-up to whole cents. A `LIVE` flight that completes with zero holdover days charges nothing. The campaign's `contracted_cents` and `net_contracted_cents` then recompute using the flight's locked `discount_pct` — the premium weeks are discounted at the same locked tier inside the per-flight net formula — the advertiser's `exposure_cents` recomputes, `delivery_posture` recomputes, and the under-delivery evaluation runs.

### 3.8. Impressions Measurement and Delivery Accounting

Every flight carries an impressions book. The `estimated_impressions` figure is computed at creation and recomputed whenever the face's `daily_traffic_count` or `illuminated` changes, but only for flights still in `HELD`, `BOOKED`, or `ART_CLEARED`. For each billing week of the booked window, the face's `daily_traffic_count` is multiplied by seven, by the illumination factor — 1.12 when the face is `illuminated`, otherwise 1.0 — and, for a `DIGITAL` face, by the slot share (`loop_slots` divided by `loop_slots_total`); each week's product is rounded half-up to a whole number of impressions, and the weekly values are then summed. The per-week rounding order is contractual.

An `OperationsAuditor` appends measurement evidence to the flight's append-only `impression_entries` list. Each entry carries a `period_start`, a `period_end`, a `source` of either `TRAFFIC_ESTIMATE` or `AUDIENCE_MEASURED`, and the measured `impressions` count, which must be a non-negative integer. Entries may be appended regardless of the flight's status, and every append re-runs the delivery replay. The append returns `201 Created` carrying the updated flight object.

The replay that produces `delivered_impressions` works like event sourcing. Entries are grouped by their exact `period_start`/`period_end` pair, and periods are processed in chronological order — ascending `period_start`, with entries inside a period ordered by their `created_at`. Within each period, measured evidence wins: if any entry in the period has source `AUDIENCE_MEASURED`, the period's value is the sum of those measured entries only; otherwise the period takes the `TRAFFIC_ESTIMATE` entry with the latest `created_at`, superseding earlier estimates rather than summing them. A late-arriving measured entry therefore retroactively replaces the estimates that preceded it for its period. The delivered total is the sum of the per-period values, and `delivery_ratio` is `delivered_impressions` divided by `estimated_impressions`, rounded half-up to 4 decimal places — and 0 when no entries exist at all or when `estimated_impressions` is 0.

### 3.9. Make-Goods and Credit Settlement

Make-goods compensate advertisers for four failures, named by `reason`: `MISSED_POSTING`, `ILLUMINATION_OUTAGE`, `PERMIT_SUSPENSION`, and `UNDER_DELIVERY`. The `credit_cents` amount is always computed server-side from the flight's economics — it is never accepted from the request body — and no credit ever exceeds the flight's `gross_cents`, the cap applied after rounding.

Each reason has its own formula. For `MISSED_POSTING`, the credit is the flight's `pinned_weekly_cents` multiplied by `missed_days` and divided by seven, rounded half-up; when a `MISSED` flight is cancelled, `missed_days` is the full booked length of `weeks` times seven, so the credit equals the entire `gross_cents`. For `ILLUMINATION_OUTAGE`, which applies only when the face is `illuminated`, the credit is `pinned_weekly_cents` multiplied by fifteen percent (0.15), multiplied by the number of outage days, and divided by seven, rounded half-up; the outage days are the flight's booked dates intersecting the span from the calendar date of the work order's `started_at` through the calendar date of its `completed_at`. For `PERMIT_SUSPENSION`, the credit is `pinned_weekly_cents` multiplied by the suspension days and divided by seven, rounded half-up; the suspension days run from `suspension_started_at` until the face's restoration — or until the flight's `end_date` when the flight completes while still suspended. For `UNDER_DELIVERY`, the guarantee is ninety percent (0.90) of `estimated_impressions`, and a credit exists only when `delivered_impressions` falls below that guarantee at completion; the credit base is the booked net — `gross_cents` reduced by the flight's locked `discount_pct`, rounded half-up, excluding holdover charges — and the credit is that base multiplied by the shortfall (the guarantee minus the delivered impressions) and divided by the guarantee, rounded half-up. Repeated evaluation is idempotent: a fresh system-proposed `UNDER_DELIVERY` record is created only while no system-proposed `UNDER_DELIVERY` record for the same flight sits in `PROPOSED`, `APPROVED`, or `APPLIED` — a `REJECTED` one does not block a fresh proposal, and manually proposed records never block the system's.

Most make-goods are proposed by the system itself: late postings (§3.6), full-flight misses (§3.5), illumination outages (§3.3), and permit suspensions (§3.2) all arrive as `PROPOSED` records with `proposed_by` set to the literal `system`. An `OperationsAuditor` may additionally propose one manually — but only with reason `UNDER_DELIVERY` and only against a `COMPLETED` flight; the manual record is born `PROPOSED` with `proposed_by` set to the auditor's `X-User-ID`. The manual credit is computed by the same `UNDER_DELIVERY` formula, so a proposal filed when no shortfall exists (or when `estimated_impressions` is 0) is still created, carrying `credit_cents` 0.

Settlement belongs to the `FinanceAnalyst`. Approval (the `PROPOSED` → `APPROVED` transition) enforces the segregation rule of §2.11: when `proposed_by` holds a user id, the approver must be a different user, otherwise `ERR_SEGREGATION_OF_DUTIES`; system-proposed credits may be approved by any finance analyst. A proposal may instead be rejected into the terminal `REJECTED` state. Applying (the `APPROVED` → `APPLIED` transition) adds `credit_cents` to the advertiser account's `credit_balance_cents` — the advertiser is resolved by following the flight's `campaign_id` to its campaign's `advertiser_id` — and recomputes the campaign's `delivery_posture`. Only `APPLIED` credits enter the balance ledger. Until a campaign's make-goods all resolve out of `PROPOSED` and `APPROVED`, its billing cannot reach `SETTLED`: the attempt fails with `ERR_UNRESOLVED_MAKE_GOODS`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — status transitions, billing moves, confirmations, verifications, and the clock advance — return `200 OK`. The table below is a navigational summary only; request payloads, preconditions, and side effects are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Advance the logical clock and run the deterministic sweep | PlatformAdmin |
| POST | `/api/rate-cards` | Create a rate card in DRAFT | InventoryManager |
| GET | `/api/rate-cards/{id}` | Get a rate card | InventoryManager, SalesPlanner |
| PUT | `/api/rate-cards/{id}` | Update rates and/or drive DRAFT→PUBLISHED→RETIRED; OCC-guarded | InventoryManager |
| GET | `/api/rate-cards/{id}/flights` | List flights that pinned this rate card | InventoryManager, SalesPlanner |
| POST | `/api/faces` | Register a face/unit | InventoryManager |
| GET | `/api/faces/{id}` | Get a face (posture, current permit, version) | InventoryManager, SalesPlanner, OperationsAuditor, ComplianceOfficer |
| PUT | `/api/faces/{id}` | Update traffic/illumination; manual status moves; decommission | InventoryManager |
| GET | `/api/faces/{id}/permits` | Permit history of the face | InventoryManager, ComplianceOfficer |
| GET | `/api/faces/{id}/maintenance-work-orders` | Work orders of the face (optional status filter) | InventoryManager, ComplianceOfficer |
| GET | `/api/faces/{id}/flights` | Flights held or booked on the face (optional status filter) | InventoryManager, SalesPlanner, OperationsAuditor |
| GET | `/api/faces/{id}/availability` | Dual committed/forward availability calendar over a window | InventoryManager, SalesPlanner |
| POST | `/api/permits` | File a permit, optionally as a superseding renewal | ComplianceOfficer |
| GET | `/api/permits/{id}` | Get a permit | ComplianceOfficer, InventoryManager |
| PUT | `/api/permits/{id}` | Reinstate (EXPIRED→ACTIVE) or revoke (→REVOKED) | ComplianceOfficer |
| GET | `/api/permits/{id}/successors` | Permits whose renewal chain points at this one | ComplianceOfficer, InventoryManager |
| POST | `/api/maintenance-work-orders` | Open a work order on a face | ComplianceOfficer |
| PUT | `/api/maintenance-work-orders/{id}` | Drive scheduling, start, completion, reopen, or cancel | ComplianceOfficer |
| POST | `/api/advertiser-accounts` | Create an advertiser | SalesPlanner |
| GET | `/api/advertiser-accounts/{id}` | Get an advertiser (exposure, credit balance, status) | SalesPlanner, SalesManager, FinanceAnalyst |
| PUT | `/api/advertiser-accounts/{id}` | Credit-hold lifecycle and credit-limit changes | FinanceAnalyst |
| GET | `/api/advertiser-accounts/{id}/campaigns` | Campaigns of an advertiser | SalesPlanner, SalesManager, FinanceAnalyst |
| POST | `/api/campaigns` | Create a campaign in DRAFT | SalesPlanner |
| GET | `/api/campaigns/{id}` | Get a campaign (computed ledgers, posture, version) | SalesPlanner, SalesManager, FinanceAnalyst, OperationsAuditor |
| PUT | `/api/campaigns/{id}` | Drive status (submit/approve/reject/cancel) or billing (invoice/settle) | SalesPlanner, SalesManager, FinanceAnalyst |
| GET | `/api/campaigns/{id}/flights` | Flights of a campaign (optional status filter) | SalesPlanner, SalesManager, FinanceAnalyst |
| POST | `/api/flights` | Create a HELD flight (space hold); OCC on face version | SalesPlanner |
| GET | `/api/flights/{id}` | Get a flight with all computed fields | SalesPlanner, SalesManager, FinanceAnalyst, OperationsAuditor, InventoryManager |
| PUT | `/api/flights/{id}` | Release, cancel, or confirm takedown of a flight | SalesPlanner, OperationsAuditor |
| POST | `/api/flights/{id}/confirm` | Confirm a HELD flight to BOOKED; OCC on campaign version | SalesPlanner |
| GET | `/api/flights/{id}/successor-flights` | Renewal successors pointing at this flight | SalesPlanner, OperationsAuditor, InventoryManager |
| GET | `/api/flights/{id}/artwork-orders` | Artwork orders of the flight | ProductionCoordinator, SalesPlanner, OperationsAuditor |
| GET | `/api/flights/{id}/posting-records` | Posting records (photo proof) of the flight | FieldInstaller, OperationsAuditor, SalesPlanner |
| GET | `/api/flights/{id}/make-goods` | Make-goods of the flight | OperationsAuditor, FinanceAnalyst, SalesPlanner |
| POST | `/api/flights/{id}/impression-entries` | Append an impressions measurement entry | OperationsAuditor |
| POST | `/api/artwork-orders` | Submit artwork production for a BOOKED flight | ProductionCoordinator |
| PUT | `/api/artwork-orders/{id}` | Drive the production pipeline including the revision loop | ProductionCoordinator |
| POST | `/api/posting-records` | Installer reports a posting with photo proof | FieldInstaller |
| PUT | `/api/posting-records/{id}` | Verify or reject photo proof | OperationsAuditor |
| POST | `/api/make-goods` | Manually propose an UNDER_DELIVERY make-good | OperationsAuditor |
| PUT | `/api/make-goods/{id}` | Approve, reject, or apply a make-good | FinanceAnalyst |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows in §2 and §3; this catalogue fixes only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_DIGITAL_SLOTS_REQUIRED` | 400 Bad Request |
| `ERR_ARTWORK_DIMENSION_MISMATCH` | 400 Bad Request |
| `ERR_MATERIAL_FACE_MISMATCH` | 400 Bad Request |
| `ERR_RATE_CARD_NOT_FOUND` | 404 Not Found |
| `ERR_FACE_NOT_FOUND` | 404 Not Found |
| `ERR_PERMIT_NOT_FOUND` | 404 Not Found |
| `ERR_WORK_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_ADVERTISER_NOT_FOUND` | 404 Not Found |
| `ERR_CAMPAIGN_NOT_FOUND` | 404 Not Found |
| `ERR_FLIGHT_NOT_FOUND` | 404 Not Found |
| `ERR_ARTWORK_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_POSTING_RECORD_NOT_FOUND` | 404 Not Found |
| `ERR_MAKE_GOOD_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_FACE_NOT_BOOKABLE` | 409 Conflict |
| `ERR_CAMPAIGN_NOT_APPROVED` | 409 Conflict |
| `ERR_CAMPAIGN_EMPTY` | 409 Conflict |
| `ERR_RATE_CARD_NOT_PUBLISHED` | 409 Conflict |
| `ERR_RATE_CARD_DUPLICATE_PUBLISHED` | 409 Conflict |
| `ERR_ADVERTISER_NOT_BOOKABLE` | 409 Conflict |
| `ERR_FACE_OVERLAP` | 409 Conflict |
| `ERR_LOOP_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_MAINTENANCE_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_FLIGHT_NOT_POSTABLE` | 409 Conflict |
| `ERR_UNRESOLVED_MAKE_GOODS` | 409 Conflict |
| `ERR_ACTIVE_ARTWORK_ORDER_EXISTS` | 409 Conflict |

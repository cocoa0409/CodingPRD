# Sports Tournament Hosting & Event Bid API — Product Requirements Document

## 1. Introduction

A sports commission that hosts sanctioned tournaments lives and dies by a long, unforgiving pipeline: a bid must be drafted against a verifiable requirement checklist and survive the sanctioning body's review; venues and hotel room blocks must be contracted under tiered rebate and attrition terms; teams must register, be seeded, and be scheduled onto real fields with real lights; certified officials must be assigned within daily workload limits and housed; volunteers must be recruited, cleared, and staffed into shifts; and when the weather turns, a disciplined rescheduling queue must absorb the disruption. After the last final, the commission owes its convention and visitors bureau an economic impact report and owes every stakeholder a settlement in which revenue, rebates, sanction fees, rentals, stipends, and expenses are accounted for under segregation-of-duties controls.

This document specifies the API through which the commission runs that entire lifecycle. The system is organized around a single **Event** aggregate whose lifecycle posture gates every child workflow: bidding happens only while the event is in a bidding posture, registration only once registration is open, scheduling only during competition setup and live play, and settlement only after completion. Around that spine the API manages finite, contended pools — hotel room-nights, field time slots, division team caps, shift seats, and officials' daily game loads — with optimistic concurrency on the few write paths where a stale view would corrupt money or lifecycle state. All endpoints are mounted under `/api/v1`.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, contract-level response formats, and cross-cutting principles that apply to every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, naming their operational capacity. The declared roles are `CommissionAdmin`, `SanctioningReviewer`, `CvbAuditor`, `TeamRep`, `Official`, `Volunteer`, `HotelManager`, `VenueManager`, and `Any`. A request missing either header, or presenting a role outside this list, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not in the endpoint's authorized set, or that violates an entity-backed ownership scope, is rejected with `ERR_FORBIDDEN` (HTTP 403).

Four roles carry an opaque identity. When `X-User-Role` is `CommissionAdmin`, `SanctioningReviewer`, `CvbAuditor`, or `Any`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `decided_by_user_id` on a bid, `evidence_submitted_by_user_id` or `verified_by_user_id` on a requirement, `created_by_user_id` or `audited_by_user_id` on an impact report, or `certified_by_user_id` and `approved_by_user_id` on a settlement, where those values anchor the segregation-of-duties checks of §2.11 — but it never compares such an identifier to any entity's `id` for ownership purposes. `CommissionAdmin` is the commission's operations staff and drives the full lifecycle. `SanctioningReviewer` is the sanctioning body's reviewer and evaluates bids. `CvbAuditor` is the convention and visitors bureau's auditor. `Any` is the read-only capacity granted to every authenticated caller on all single-resource, list, filtered-list, and summary reads.

Five roles are entity-backed. When `X-User-Role` is `TeamRep`, `X-User-ID` is the `id` of the acting Team; ownership checks on any resource that references a Team compare the resource's team field to `X-User-ID` (a team representative may act only on their own team and their own team's bookings). When `X-User-Role` is `Official`, `X-User-ID` is the `id` of the acting Official; ownership checks compare an assignment's or booking's `official_id` to `X-User-ID`. When `X-User-Role` is `Volunteer`, `X-User-ID` is the `id` of the acting Volunteer; ownership checks compare a signup's `volunteer_id` — or the `volunteer_id` supplied in a signup request — to `X-User-ID`. When `X-User-Role` is `HotelManager`, `X-User-ID` is the `id` of the HotelBlock the manager operates; ownership checks compare the path's block or a booking's `hotel_block_id` to `X-User-ID`. When `X-User-Role` is `VenueManager`, `X-User-ID` is the `id` of the Venue the manager operates; ownership checks on a field compare the field's `venue_id` to `X-User-ID`.

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

List endpoints paginate through two query parameters. `limit` caps the number of returned items: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips a number of items and defaults to 0. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

Unless a list's own description says otherwise, list endpoints sort by `created_at` ascending. Several lists deliberately override that default — the event list sorts by `created_at` descending, the bid list by `cycle_number` descending, and the field, division, and official lists by `name` ascending; each such override is stated in §3 alongside the workflow that owns the list.

### 2.4. The Logical Clock

The server maintains a logical clock rather than reading wall-clock time. Its startup default is exactly 2026-08-01T00:00:00Z, and it never falls back to real time. Every date- and datetime-dependent rule in this document — hotel cutoff dates, booking check-in and no-show eligibility, event date ranges, shift completion windows, blackout windows — reads this clock, and every `created_at` and `updated_at` timestamp in the system is stamped from it.

An admin-only, test-driving capability advances the clock: a `CommissionAdmin` supplies a `to_iso8601` instant and the clock moves to it, reporting the new value as `current_utc`. The clock is monotonic — attempting to set it to an earlier instant than its current value is rejected with `ERR_VALIDATION` (HTTP 400).

### 2.5. Event Posture: The Master Lifecycle Gate

An Event's `posture` is the single gate that decides which child workflows are legal at any moment. The full posture vocabulary is `BIDDING`, `AWARDED`, `PLANNING`, `REGISTRATION_OPEN`, `COMPETITION_SETUP`, `LIVE`, `COMPLETED`, `SETTLED`, `BID_LOST`, and `CANCELLED`. A new event begins in `BIDDING` with `version` 1. The happy-path ladder runs `BIDDING` → `AWARDED` → `PLANNING` → `REGISTRATION_OPEN` → `COMPETITION_SETUP` → `LIVE` → `COMPLETED` → `SETTLED`; `BID_LOST` and `CANCELLED` are off-ladder outcomes. Any operation attempted in a posture that does not permit it is rejected with `ERR_EVENT_POSTURE_FORBIDS` (HTTP 409); a posture advance that names a target the current posture cannot reach is rejected with `ERR_INVALID_STATE` (HTTP 409).

The posture gates, stated once here and referenced throughout §3, are: bid creation is legal while the event is `BIDDING`, `BID_LOST`, or `SETTLED`, while bid submission additionally requires `BIDDING`. Venue contracting and hotel-block contracting require `BIDDING`, `AWARDED`, or `PLANNING`. Team registration requires `REGISTRATION_OPEN`. Match scheduling and weather-alert activation require `COMPETITION_SETUP` or `LIVE` (alert creation itself is ungated and may occur in any non-terminal posture). Impact report creation and settlement creation require `COMPLETED`. Team check-in, match start, and match finalization require `LIVE`.

Posture advances are performed by a `CommissionAdmin` through a posture-advance request that names its target in `to_posture` and carries `expected_event_version` per §2.8. Each advance has its own readiness precondition:

- `AWARDED` → `PLANNING` requires at least one venue of the event in `CONTRACTED` status and at least one hotel block in `CONTRACTED` status.
- `PLANNING` → `REGISTRATION_OPEN` requires at least one division to exist for the event.
- `REGISTRATION_OPEN` → `COMPETITION_SETUP` requires that every division whose `eligible_team_count` meets or exceeds its `min_teams` is in `SEEDING_LOCKED`, `BRACKET_PUBLISHED`, or `COMPLETED`. As a side effect, each division below its minimum is cancelled to `CANCELLED` (each such division's `version` increments by one), and every team of a cancelled division in `ENTERED`, `WAITLISTED`, `ROSTER_SUBMITTED`, or `ELIGIBLE` status becomes `WITHDRAWN` (each team's `version` increments by one).
- `COMPETITION_SETUP` → `LIVE` requires every division of the event to be in `BRACKET_PUBLISHED`, `COMPLETED`, or `CANCELLED`.
- `LIVE` → `COMPLETED` requires that no match of the event remains in `PENDING_TEAMS`, `SCHEDULED`, `WEATHER_DELAYED`, `RESCHEDULE_QUEUE`, or `IN_PROGRESS`.
- `COMPLETED` → `SETTLED` is not manual: it happens automatically when the event's settlement is paid (see §3.9), and it requires an impact report of the event to be `ACCEPTED`. Its cascade moves every hotel block in `RECONCILED` to `SETTLED` (each block's `version` increments by one, with `final_rebate_cents` and `attrition_penalty_cents` frozen).

Two rungs of the ladder are climbed by the system rather than by a posture request. When a bid is awarded, the event moves `BIDDING` → `AWARDED` and every other bid of the event in `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, or `REVISION_REQUESTED` becomes `SUPERSEDED` (each such bid's `version` increments by one). When a bid is rejected, the event moves `BIDDING` → `BID_LOST`. Renewal runs the ladder backward: creating a fresh bid on a `BID_LOST` event revives it to `BIDDING`, and creating a renewal bid on a `SETTLED` event re-enters `BIDDING` for the next hosting cycle with the event's `active_bid_id` pointed at the new bid. In both revivals the bid-create request performs a single `Event.version` increment that covers both the bid creation and the posture revival.

Cancellation is available to a `CommissionAdmin` from `BIDDING`, `AWARDED`, `PLANNING`, `REGISTRATION_OPEN`, or `COMPETITION_SETUP`, always landing on the absorbing `CANCELLED` posture. The cancellation cascade grows as the event matures: from `BIDDING`, the event's bids in `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, or `REVISION_REQUESTED` become `WITHDRAWN`. From `AWARDED` or `PLANNING`, hotel blocks in `NEGOTIATING` or `CONTRACTED` are additionally `RELEASED`, and room bookings in `RESERVED` or `CONFIRMED` are cancelled with no fee. From `REGISTRATION_OPEN`, teams in `ENTERED`, `WAITLISTED`, `ROSTER_SUBMITTED`, or `ELIGIBLE` additionally become `WITHDRAWN`. From `COMPETITION_SETUP`, matches in `PENDING_TEAMS`, `SCHEDULED`, or `RESCHEDULE_QUEUE` additionally become `CANCELLED`, and assignments on those matches in `PROPOSED` or `ACCEPTED` are released with `released_reason` `MATCH_CANCELLED`. Every entity touched by any of these cascades has its `version` incremented and its `updated_at` refreshed, and the event's own `version` increments once per posture change.

### 2.6. Common Resource Properties

All eighteen resource types in this API — events, bids, bid requirements, venues, fields, hotel blocks, room bookings, divisions, teams, matches, officials, official assignments, volunteers, shifts, shift signups, weather alerts, impact reports, and settlements — carry the same four system-managed properties:

- `id` (string): a server-minted UUID with no type prefix. The `id` serves identity only and is never consulted in ranking, tie-break, or allocation decisions.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, stamped from the logical clock at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource, including cascaded mutations triggered by another resource's operation.
- `version` (integer): starts at 1 at creation and increments by exactly one on every mutation, again including cascades. A single client request can therefore advance the `version` of many related entities at once.

### 2.7. Money, Precision, and Rounding

All monetary values are represented as integer cents — venue rental fees, room rates, booking charges, registration fees, rebates, penalties, stipends, sponsor contributions, expense amounts, and every settlement total. Rounding, where a calculation produces a fractional cent, is always round half up to whole cents. Two calculations deliberately pin a per-item rounding order — the hotel rebate rounds each booking's rebate before summing, and the sanction fee rounds each tier slice before summing — because rounding once at the end yields a different total and is non-conformant; §3.3 and §3.9 state those orders where the calculations live.

Two non-money quantities have their own precision contracts. The hotel pickup ratio is computed to four decimal places, round half up. Volunteer credited hours and `hours_worked` are expressed with two decimal places, round half up.

### 2.8. Optimistic Concurrency Control

Four write endpoints require the caller to prove it has observed the current state of the parent entity by carrying an expected-version field. In each case, if the supplied value does not equal the parent entity's current `version` — because another write has advanced that version since the client last read the entity — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no change is applied.

- `POST /api/v1/events/{id}/bids` — creating a bid on an event requires `expected_event_version` matching the event's current `version`. Bid creation legitimately supersedes an existing draft bid and can revive a lost or settled event, so a writer holding a stale event view must restart from a fresh read.
- `PATCH /api/v1/bids/{id}` — editing a bid's notes requires `expected_bid_version` matching the bid's current `version`, because requirement verifications and reviewer actions mutate the bid's review surface between reads.
- `PATCH /api/v1/hotel-blocks/{id}` — editing a negotiating hotel block's terms requires `expected_hotel_block_version` matching the block's current `version`; bookings pin their rate from the block, so repricing from a stale view would corrupt already-quoted offers.
- `POST /api/v1/events/{id}/posture` — advancing an event's posture requires `expected_event_version` matching the event's current `version`, because posture transitions fire multi-entity cascades whose preconditions were evaluated against the version the client observed.

Endpoints not listed here take no version field; the expected-version field on these four endpoints is non-optional.

### 2.9. Validation Order and Nested Resource Retrieval

When several checks could reject the same request, the server applies them in a fixed order so that the surfaced error is deterministic. Authentication comes first: missing or unknown identity surfaces as `ERR_UNAUTHENTICATED` before anything else is examined. Authorization and entity-backed ownership follow, surfacing `ERR_FORBIDDEN`. Existence comes next, then the optimistic-concurrency version check (`ERR_STALE_VERSION`), then event-posture gating (`ERR_EVENT_POSTURE_FORBIDS`), then entity-state legality (`ERR_INVALID_STATE` or the more specific state errors such as `ERR_BID_NOT_EDITABLE`, `ERR_DIVISION_NOT_OPEN`, `ERR_MATCH_NOT_SCHEDULABLE`, or `ERR_BLOCK_NOT_CONTRACTED`). Segregation-of-duties checks (`ERR_SOD_VIOLATION`) run after state legality, followed by business-constraint checks (completeness, uniqueness, duplication, score thresholds), then temporal window rules, then cross-event referential integrity (`ERR_CROSS_EVENT_REFERENCE`), and finally capacity and fiscal limits (room inventory, shift capacity, daily assignment limits, block reconcilability).

Existence checking on nested paths proceeds strictly left to right: the event first, then the child, then the grandchild. A request addressing a field under a non-existent venue, or a booking under a non-existent block, is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve, before later path segments or body rules are considered. References supplied in the request body — `field_id`, `official_id`, `volunteer_id`, `team_id`, and similar — are existence-checked at the same stage.

Malformed request bodies, missing required fields, invalid enum members, out-of-range numbers, and inverted date ranges are rejected with `ERR_VALIDATION` (HTTP 400). A body so malformed it cannot be interpreted is detected before any state evaluation; semantic range violations surface with the pinned error identifiers described in §3.

### 2.10. Cascading Consistency and Terminal States

State changes propagate. When a parent transitions in a way that resolves its children — an event cancelled, a division locked, a field blacked out, a weather alert activated, a shift completed, a settlement paid — every affected child entity transitions with it, and each touched entity independently increments its `version` by one and refreshes its `updated_at`. Derived counters such as a division's `entered_team_count`, a shift's `confirmed_count`, a block's `picked_up_room_nights`, and an official's `assigned_game_count` are recomputed as part of the same operation, never left stale.

Terminal states are absorbing: any further transition attempted on an entity already in a terminal state is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409). The terminal states are: event `CANCELLED`; bid `AWARDED`, `REJECTED`, `WITHDRAWN`, `SUPERSEDED`; requirement `VERIFIED`, `WAIVED`; venue `RELEASED`; hotel block `SETTLED`, `RELEASED`; booking `CHECKED_OUT`, `CANCELLED`, `NO_SHOW`; division `COMPLETED`, `CANCELLED`; team `ELIMINATED`, `FINISHED`, `CHAMPION`, `WITHDRAWN`, `DISQUALIFIED`; match `FINAL`, `FORFEITED`, `CANCELLED`; official `INACTIVE`; assignment `DECLINED`, `RELEASED`, `WORKED`; volunteer `REJECTED`, `INACTIVE`; shift `COMPLETED`, `CANCELLED`; signup `WORKED`, `NO_SHOW`, `CANCELLED`; weather alert `RESOLVED`, `EXPIRED`; impact report `ACCEPTED`; settlement `PAID`. A field has no terminal state — `AVAILABLE` and `BLACKED_OUT` cycle freely. Note that the `SETTLED` event posture, while not terminal in this sense, is left only through the renewal-bid revival of §2.5, and `BID_LOST` revives only the same way.

### 2.11. Segregation of Duties

Three operations are forbidden to the operator who originated the work, and each breach is rejected with `ERR_SOD_VIOLATION` (HTTP 403). A `SanctioningReviewer` may not verify requirement evidence they submitted themselves: the reviewer's `X-User-ID` must differ from the requirement's `evidence_submitted_by_user_id`. A `CvbAuditor` may not audit an impact report they created: the auditor's `X-User-ID` must differ from the report's `created_by_user_id`. And the administrator approving a settlement must not be the administrator who certified it: the approver's `X-User-ID` must differ from the settlement's `certified_by_user_id`.

## 3. Business Logic & Workflows

### 3.1. Events, Bids, and the Requirement Checklist

A `CommissionAdmin` opens the lifecycle by creating an event with a display `name`, the `sanctioning_body` the bid will be submitted to, the `host_city`, and the event's first and last days `starts_on` and `ends_on`, both ISO calendar dates with `ends_on` on or after `starts_on`. The event is born in `BIDDING` posture with `version` 1 and no active bid. Two counters are maintained on the event as its children evolve: `registered_team_count`, the number of the event's teams in `ENTERED`, `ROSTER_SUBMITTED`, `ELIGIBLE`, `CHECKED_IN`, `ELIMINATED`, `FINISHED`, `CHAMPION`, or `DISQUALIFIED` status, and `finalized_match_count`, the number of its matches in `FINAL` or `FORFEITED`. A computed operational summary view per event reports its `posture`, `registered_team_count`, `finalized_match_count`, `active_bid_id`, plus two rollup figures used by stakeholders during planning and settlement: `total_final_rebate_cents`, the sum of final rebates across the event's hotel blocks, and `picked_up_room_nights_total`, the sum of picked-up room-nights across those blocks. The event list sorts by `created_at` descending — newest first — and accepts `posture` and `active_bid_id` filters, the latter locating the event that currently points at a given bid.

While an event is `BIDDING`, `BID_LOST`, or `SETTLED`, a `CommissionAdmin` may create a bid against it, carrying `expected_event_version` (per §2.8) and optional free-form `notes`. Each bid belongs to one event through its `event_id` and receives a `cycle_number`: one-based, incrementing per new bid, so a renewal bid for the next hosting cycle continues the sequence rather than restarting it. An event has at most one non-terminal bid at a time. Creating a new bid supersedes an existing `DRAFT` bid — the old draft becomes `SUPERSEDED` and its `version` increments — but an active bid in `SUBMITTED`, `UNDER_REVIEW`, or `REVISION_REQUESTED` blocks creation outright with `ERR_BID_ALREADY_ACTIVE` (HTTP 409). A bid on a `BID_LOST` or `SETTLED` event revives the event to `BIDDING` as described in §2.5; in every case the event's `active_bid_id` is set to the new bid, and the event's `version` increments once for the whole operation. The bid list sorts by `cycle_number` descending and accepts a `status` filter.

A bid begins in `DRAFT`. While it is `DRAFT` or `REVISION_REQUESTED` it remains editable: a `CommissionAdmin` may patch its `notes` (carrying `expected_bid_version` per §2.8) and may add requirements to its checklist. Attempting those edits on a bid in any other status is rejected with `ERR_BID_NOT_EDITABLE` (HTTP 409).

Each checklist requirement belongs to its bid through `bid_id` and carries a `kind` drawn from `VENUE_CONTRACT`, `HOTEL_BLOCKS`, `INSURANCE_CERT`, `FINANCIAL_GUARANTEE`, `VOLUNTEER_PLAN`, `MEDICAL_PLAN`, `TRANSPORT_PLAN`, or `LEGACY_PLAN`; an `is_mandatory` flag; a scoring `weight_points` between 1 and 100 inclusive; and optional `notes`. Mandatory requirements must reach `VERIFIED` before the bid can be submitted and can never be waived. Requirements are created in `PENDING` status and are listed in `created_at` ascending order, filterable by `status`.

Evidence flows through each requirement. A `CommissionAdmin` submits evidence for a `PENDING` or `RETURNED` requirement by supplying an `evidence_uri` (and optional `notes`), moving it to `EVIDENCE_SUBMITTED` and stamping `evidence_submitted_by_user_id` with the submitter's `X-User-ID`; resubmission on a `RETURNED` requirement overwrites the previous `evidence_uri` and submitter. The parent bid must be `DRAFT` or `REVISION_REQUESTED`, otherwise `ERR_BID_NOT_EDITABLE`. A `SanctioningReviewer` then adjudicates: a verify action with `decision` `VERIFIED` or `RETURNED` (with optional `review_notes` recorded on the requirement) is legal only on an `EVIDENCE_SUBMITTED` requirement — verifying anything else is rejected with `ERR_REQUIREMENT_NOT_REVIEWABLE` (HTTP 409) — and the reviewer's `X-User-ID` must differ from `evidence_submitted_by_user_id` per §2.11. Verification stamps `verified_by_user_id` and recomputes the parent bid's `review_score`; returning sends the requirement back for new evidence. Alternatively, a reviewer may waive a requirement by supplying a `waiver_reason`: waiving is legal only from `PENDING` (anything else draws `ERR_REQUIREMENT_NOT_REVIEWABLE`), only while the parent bid is `DRAFT` or `REVISION_REQUESTED` (`ERR_BID_NOT_EDITABLE`), and never on a mandatory requirement (`ERR_REQUIREMENT_NOT_WAIVABLE`, HTTP 409). A waiver also recomputes the bid's `review_score`.

The `review_score` is the bid's weighted completeness score: the sum of `weight_points` over all `VERIFIED` requirements, plus half of each `WAIVED` requirement's `weight_points` rounded down to a whole number. It is recomputed on every verify and every waive.

Submitting the bid is the checklist's moment of truth, enforced in order: the event must be in `BIDDING` posture (otherwise `ERR_EVENT_POSTURE_FORBIDS`); every mandatory requirement must be `VERIFIED`; and every requirement of the bid, mandatory or not, must be in `VERIFIED` or `WAIVED` — any shortfall is rejected with `ERR_BID_REQUIREMENTS_INCOMPLETE` (HTTP 409). A successful submit moves the bid to `SUBMITTED` and stamps `submitted_at` from the logical clock. The sanctioning body then opens review, moving `SUBMITTED` → `UNDER_REVIEW`, and may either request revisions — carrying `revision_notes` and moving `UNDER_REVIEW` → `REVISION_REQUESTED` — or decide the bid. The revision loop is cyclic: `UNDER_REVIEW` → `REVISION_REQUESTED` → `SUBMITTED` → `UNDER_REVIEW`, and each resubmission from `REVISION_REQUESTED` re-enforces the same requirement gates, re-stamps `submitted_at`, and increments the bid's `revision_count` (which counts exactly those resubmissions, starting from 0).

The decide action takes a `decision` of `AWARDED` or `REJECTED`. Awarding requires a `review_score` of at least 80 points — the boundary is inclusive — and a score below that threshold is rejected with `ERR_BID_SCORE_BELOW_THRESHOLD` (HTTP 409). Either decision stamps `decided_at` from the logical clock and `decided_by_user_id` with the reviewer's `X-User-ID`. An award cascades the event `BIDDING` → `AWARDED` and supersedes the event's other non-terminal bids; a rejection cascades the event `BIDDING` → `BID_LOST`. A `CommissionAdmin` may also withdraw a bid from `DRAFT`, `SUBMITTED`, or `REVISION_REQUESTED`, moving it to `WITHDRAWN` and clearing the event's `active_bid_id`. `AWARDED`, `REJECTED`, `WITHDRAWN`, and `SUPERSEDED` are terminal for a bid.

### 3.2. Venue and Field Contracting

Venue negotiations begin as soon as bidding does. A `CommissionAdmin` creates a venue under an event with a `name`, street `address`, a flat `rental_fee_cents` in cents (zero or more), and a `revenue_share_pct` expressed as a fraction between 0 and 0.5 inclusive. The venue starts `PROPOSED`. Executing the agreement — supplying the executed document's `contract_uri` — moves it to `CONTRACTED` and is legal only while the event is `BIDDING`, `AWARDED`, or `PLANNING`; otherwise the request is rejected with `ERR_EVENT_POSTURE_FORBIDS`. A contracted venue can later be released to `RELEASED`, but only while none of its fields hosts a match in `SCHEDULED`, `WEATHER_DELAYED`, `RESCHEDULE_QUEUE`, or `IN_PROGRESS` — a release attempted against active matches fails with `ERR_VENUE_HAS_ACTIVE_MATCHES` (HTTP 409). Venues list in `created_at` ascending order with an optional `status` filter.

Fields belong to venues. A `CommissionAdmin`, or the `VenueManager` of that venue, creates a field on a contracted venue with a `name`, a `surface_type` of `TURF`, `GRASS`, `COURT`, or `INDOOR`, a `has_lights` flag, and a `slot_minutes` match-slot length between 30 and 180 minutes inclusive. `has_lights` is not decorative: §3.5 forbids scheduling a match that starts at or after 18:00 local onto a field without lights. Fields are born `AVAILABLE` and list in `name` ascending order; the matches played on a field list by `scheduled_start` ascending with unscheduled matches last, ties broken by `created_at` ascending.

Either a `CommissionAdmin` or the venue's own `VenueManager` may black out a field for a window by supplying `blackout_start`, `blackout_end`, and a `reason`. The blackout requires the owning venue to be `CONTRACTED` (otherwise `ERR_INVALID_STATE`, HTTP 409) and the window to be well formed with `blackout_end` strictly after `blackout_start` (otherwise `ERR_VALIDATION`, HTTP 400). Blacking out moves the field to `BLACKED_OUT` and records the window — and it does not silently move matches: every match on the field in `SCHEDULED` status whose half-open playing window intersects the blackout window is pushed into `RESCHEDULE_QUEUE` (each match's `version` increments, and its `original_scheduled_start` is preserved), while assignments on those matches in `PROPOSED` or `ACCEPTED` are released with `released_reason` `MATCH_CANCELLED` and each affected official's `assigned_game_count` is recomputed. Lifting the blackout returns the field to `AVAILABLE` and clears the window; the `AVAILABLE` ↔ `BLACKED_OUT` pair is cyclic, and enqueued matches wait for §3.6's rescheduling discipline.

### 3.3. Hotel Blocks, Room Bookings, and Rebate Economics

Hotel inventory is negotiated per event as a set of blocks. A `CommissionAdmin` creates a block with the `hotel_name`, `contracted_rooms_per_night` (at least 1), the negotiated nightly `room_rate_cents` (at least 1 cent), the block's first night `block_start_date`, the day after its last night `block_end_date` (strictly after the start), the `cutoff_date` — the last day on which new bookings and fee-free cancellations are accepted — and an `attrition_allowance_pct`, the allowed slippage fraction before an attrition penalty applies, between 0 and 0.5 inclusive. A new block is `NEGOTIATING` with `picked_up_room_nights` 0, `estimated_rebate_cents` 0, and `rebate_tier` `TIER_0`. Blocks list in `created_at` ascending order, filterable by `status`.

While a block is `NEGOTIATING`, a `CommissionAdmin` may revise `contracted_rooms_per_night`, `room_rate_cents`, `cutoff_date`, or `attrition_allowance_pct`, carrying `expected_hotel_block_version` per §2.8; once the block has left `NEGOTIATING` the same edit is rejected with `ERR_BLOCK_NOT_CONTRACTED` (HTTP 409). Executing the agreement moves the block to `CONTRACTED` and, like venue contracting, requires the event to be `BIDDING`, `AWARDED`, or `PLANNING`. Later, a `CommissionAdmin` closes the booking window — legal only once the logical clock's date has passed `cutoff_date`, otherwise `ERR_CUTOFF_PASSED` (HTTP 409) — moving the block to `CUTOFF_PASSED`. Reconciliation, performed by a `CommissionAdmin` or by the block's own `HotelManager`, requires the block to be `CUTOFF_PASSED` — reconciling a block in any other status is rejected with `ERR_BLOCK_NOT_RECONCILABLE` (HTTP 409) — and moves the block to `RECONCILED`, computing and freezing `final_rebate_cents`, `attrition_penalty_cents`, and `rebate_tier` per the final rebate variant below. Reconciled blocks move to `SETTLED` automatically when the settlement is paid, and a block in `CONTRACTED` is `RELEASED` by the event-cancellation cascade, which cancels its `RESERVED` and `CONFIRMED` bookings without fee.

Bookings live inside a contracted block. A booking records its `hotel_block_id`, a `booker_type` of `TEAM`, `OFFICIAL`, or `COMMISSION`, the lead `guest_name`, a `rooms_count` of at least 1, and the stay window `check_in_date` to `check_out_date` — the booking occupies the nights from check-in up to but not including check-out, so the night count is the number of days between the two dates. When `booker_type` is `TEAM` the booking must carry the booking team's `team_id`; when it is `OFFICIAL` it must carry the official's `official_id` (this is how officials' housing is booked); otherwise the corresponding field is null. A `TeamRep` books for their own team and an `Official` books for themselves; a `CommissionAdmin` may book any type including `COMMISSION`, and referenced teams or officials must belong to the same event or the create fails with `ERR_CROSS_EVENT_REFERENCE` (HTTP 409).

At creation the booking pins its `rate_cents` from the block's current `room_rate_cents`; later changes to the block's rate never reprice an existing booking. Two values derive from the pin: `room_nights`, the `rooms_count` multiplied by the number of nights in the stay window, and `total_charge_cents`, the `room_nights` multiplied by the pinned `rate_cents`. Creation is guarded in the order of §2.9: the block must be `CONTRACTED` (otherwise `ERR_BLOCK_NOT_CONTRACTED`); the logical clock's date must be on or before `cutoff_date` (a booking after cutoff is rejected with `ERR_CUTOFF_PASSED`); every occupied night must lie within the block's window from `block_start_date` up to but not including `block_end_date` (otherwise `ERR_BOOKING_OUTSIDE_BLOCK_DATES`, HTTP 422); and per-night inventory must hold — for every night of the stay, the sum of `rooms_count` over all non-`CANCELLED` bookings occupying that night, plus the new booking's `rooms_count`, must not exceed `contracted_rooms_per_night` (otherwise `ERR_BLOCK_INVENTORY_EXCEEDED`, HTTP 409). A booking is born `RESERVED`, and the block's `picked_up_room_nights` — the sum of `room_nights` over bookings in `RESERVED`, `CONFIRMED`, `CHECKED_IN`, `CHECKED_OUT`, or `NO_SHOW` — is recomputed to include it immediately. Bookings list by `check_in_date` ascending then `created_at` ascending, and the filtered booking list additionally accepts `hotel_block_id`, `team_id`, `official_id`, and `status` filters.

The booking lifecycle runs through explicit actions supplied as `action`: `CONFIRM`, `CHECK_IN`, `CHECK_OUT`, `CANCEL`, and `NO_SHOW`. Confirming a `RESERVED` booking requires the parent block to be `CONTRACTED` (otherwise `ERR_BLOCK_NOT_CONTRACTED`) and moves it to `CONFIRMED`; pickup is unchanged because the booking already counted. Check-in requires the logical clock's date to be on or after `check_in_date` (otherwise `ERR_VALIDATION`) and moves `CONFIRMED` → `CHECKED_IN`; check-out moves `CHECKED_IN` → `CHECKED_OUT`. Cancelling is possible from `RESERVED` or `CONFIRMED` — by a `CommissionAdmin`, the block's `HotelManager`, the `TeamRep` of the booking's own team, or the `Official` of their own booking — while the other lifecycle actions belong to a `CommissionAdmin` or the block's `HotelManager`. Cancellation computes `cancellation_fee_cents`: zero when the logical clock's date is on or before `cutoff_date`, otherwise half of the booking's `rooms_count` multiplied by its pinned `rate_cents`, rounded half up to whole cents; the field defaults to 0 and the block's `picked_up_room_nights` drops by the cancelled booking's `room_nights`. Marking a `CONFIRMED` booking `NO_SHOW` requires the clock's date to be strictly after `check_in_date` (otherwise `ERR_VALIDATION`), and by convention a no-show's `room_nights` still count toward pickup for attrition purposes.

The rebate structure rewards pickup. The block's contracted supply is `contracted_rooms_per_night` multiplied by the number of nights in the block window (the days from `block_start_date` up to but not including `block_end_date`). The pickup ratio is `picked_up_room_nights` divided by that supply, rounded half up to four decimal places. The tier ladder reads: a ratio of at least 1.0000 earns `TIER_3` at a rate of 0.12; at least 0.9000 earns `TIER_2` at 0.10; at least 0.8000 earns `TIER_1` at 0.07; anything lower is `TIER_0` with no rebate. The rebate itself is computed booking by booking: each in-set booking's `total_charge_cents` is multiplied by the tier rate and rounded half up to whole cents first, and those rounded per-booking amounts are then summed. Rounding the block-level product once is a different, non-conformant number.

Two variants of this calculation exist, and they differ only in which bookings count. The estimated variant — exposed as `estimated_rebate_cents` and recomputed on every read of the block before reconcile — is forward-looking and counts bookings in `RESERVED`, `CONFIRMED`, `CHECKED_IN`, `CHECKED_OUT`, or `NO_SHOW`, including bookings that may still cancel; `rebate_tier` follows this estimated computation and sits at `TIER_0` until it is computable. The final variant runs once, at reconcile, and counts only actualized pickup — bookings in `CHECKED_OUT` or `NO_SHOW`; it writes `final_rebate_cents` (null before reconcile), freezes `rebate_tier`, and on identical data yields a rebate lower than or equal to the estimate.

Attrition punishes slippage. The attrition floor is one minus `attrition_allowance_pct`. When the pickup ratio falls below that floor, the shortfall in room-nights is the floor multiplied by the contracted supply, rounded down to a whole number, minus `picked_up_room_nights`; the `attrition_penalty_cents` is that shortfall multiplied by the block's `room_rate_cents` and then by one half, rounded half up to whole cents. When the ratio meets or exceeds the floor, the penalty is zero. Like the rebate, the penalty is null until reconcile computes it.

### 3.4. Divisions, Registration, and the Waitlist

Competition is organized into divisions under an event. A `CommissionAdmin` creates a division with a `name` (for example an age-and-gender label), a `team_cap` of at least 2 capping the number of entered-or-later teams, a `min_teams` of at least 2 and no more than `team_cap` — the minimum eligible field required to lock seeding — and a `registration_fee_cents` of zero or more, the entry fee owed per fee-paid team. A division opens in `OPEN` status; divisions list by `name` ascending with an optional `status` filter, and the division completes to `COMPLETED` automatically once every one of its matches has reached `FINAL`, `FORFEITED`, or `CANCELLED`.

Two counters summarize a division's registration posture. `entered_team_count` counts its teams in `ENTERED`, `ROSTER_SUBMITTED`, `ELIGIBLE`, `CHECKED_IN`, `ELIMINATED`, `FINISHED`, `CHAMPION`, or `DISQUALIFIED`; `eligible_team_count` counts the narrower set `ELIGIBLE`, `CHECKED_IN`, `ELIMINATED`, `FINISHED`, and `CHAMPION`.

Once the event reaches `REGISTRATION_OPEN`, a `CommissionAdmin` registers teams into a division with a `name`, a primary `contact_email`, and a `strength_rating` between 1 and 100 inclusive that will drive seeding. Registration against any other posture is rejected with `ERR_EVENT_POSTURE_FORBIDS`. The cap decides the new team's initial `status`: while `entered_team_count` is below `team_cap` the team enters as `ENTERED`; once the cap is reached, overflow teams become `WAITLISTED`. Teams list by `seed_number` ascending with unseeded teams last, then `strength_rating` descending, then `created_at` ascending.

From `ENTERED`, the team's own `TeamRep` submits its roster, supplying `roster_player_count` and optional `roster_notes`. The division must still be `OPEN` (otherwise `ERR_DIVISION_NOT_OPEN`, HTTP 409) and the roster must field at least 7 players (a smaller `roster_player_count` is rejected with `ERR_ROSTER_TOO_SMALL`, HTTP 422), moving the team to `ROSTER_SUBMITTED`. A `CommissionAdmin` then verifies eligibility — again requiring the division to be `OPEN` — moving `ROSTER_SUBMITTED` → `ELIGIBLE` and recomputing the division's `eligible_team_count`. On event days, check-in moves an `ELIGIBLE` team to `CHECKED_IN`; it can be performed by a `CommissionAdmin` or the team's own `TeamRep`, requires the event to be `LIVE` (otherwise `ERR_EVENT_POSTURE_FORBIDS`), and applies only to a team still `ELIGIBLE` (otherwise `ERR_INVALID_STATE`).

Withdrawal releases a team back out of the competition. A `CommissionAdmin` or the team's own `TeamRep` may withdraw a team from `ENTERED`, `WAITLISTED`, or `ROSTER_SUBMITTED`, and from `ELIGIBLE` while the division is still `OPEN` — a manual withdrawal of an eligible team after the division has left `OPEN` is rejected with `ERR_DIVISION_NOT_OPEN`. When an `ENTERED` or `ELIGIBLE` team withdraws while the division is `OPEN` and a waitlist exists, the oldest `WAITLISTED` team by `created_at` ascending is promoted to `ENTERED` automatically (its `version` increments and `entered_team_count` is recomputed); no waitlisted team can exist past seeding lock, so the promotion is a registration-window mechanism. Withdrawals in any of these states recompute the division's `entered_team_count`.

Disqualification is harsher and is reserved for a `CommissionAdmin` supplying a `reason`. Disqualifying an `ELIGIBLE` team clears its slot to null in any `PENDING_TEAMS` match that contains it. Disqualifying a `CHECKED_IN` team does that and more: every match containing the team in `SCHEDULED` or `IN_PROGRESS` becomes `FORFEITED` with the opponent recorded as winner and the same advancement cascade as a normal finalization (§3.6), and assignments on those forfeited matches in `PROPOSED` or `ACCEPTED` are released with `released_reason` `MATCH_CANCELLED` while each affected official's `assigned_game_count` is recomputed.

### 3.5. Seeding, Bracket Publication, and Match Scheduling

When registration closes around a division, a `CommissionAdmin` locks its seeding. Locking requires the event to be in `REGISTRATION_OPEN` (otherwise `ERR_EVENT_POSTURE_FORBIDS`) and the division's `eligible_team_count` to meet or exceed its `min_teams` (otherwise `ERR_DIVISION_BELOW_MIN_TEAMS`, HTTP 409), and the division itself must still be `OPEN` (otherwise `ERR_DIVISION_NOT_OPEN`). Locking moves the division to `SEEDING_LOCKED` and performs the seeding: the division's `ELIGIBLE` teams are ordered by `strength_rating` descending, ties broken by `created_at` ascending — the earlier-registered team seeds higher, with three-fractional-digit timestamp precision — and `seed_number` values 1 through N are assigned in that order. A team's `seed_number` is null until seeding assigns it, and the `id` is never consulted in this ordering. Teams of the division still in `ENTERED`, `WAITLISTED`, or `ROSTER_SUBMITTED` are withdrawn to `WITHDRAWN`, each incrementing its `version`.

Publishing the bracket requires `SEEDING_LOCKED` and an event posture of `REGISTRATION_OPEN` or `COMPETITION_SETUP`, and moves the division to `BRACKET_PUBLISHED`. Publication generates the division's matches. The `bracket_size` is the smallest power of two that is greater than or equal to the seeded team count, and never smaller than two; `total_rounds` is the base-2 logarithm of the bracket size, so `round_number` 1 is the first round and `round_number` equal to `total_rounds` is the final. The number of byes is the bracket size minus the seeded count, and byes go to seeds 1 through the bye count in order. Each first-round real match pairs seed s with the seed whose number is the bracket size plus one minus s, for every seed s in the lower half of the seeding list that did not receive a bye; the total number of matches created is the bracket size minus one minus the number of byes. Every match records its `division_id`, `round_number`, and one-based `bracket_slot` within the round, and knows its successor through `winner_advances_to_match_id`: the winner of the match in round r at slot k advances to the match in round r+1 at the slot given by k divided by two rounded up, filling that successor's `home_team_id` when k is odd and its `away_team_id` when k is even. The final has no successor, so its `winner_advances_to_match_id` is null. Seeds holding byes are placed directly into their round-two match slots at publish time. All other matches begin in `PENDING_TEAMS` with `home_team_id` and `away_team_id` null until seeding or advancement fills them, and a division's matches list by `round_number` ascending then `bracket_slot` ascending, filterable by `status` or `round_number`.

Scheduling places a `PENDING_TEAMS` match onto a field. A `CommissionAdmin` supplies the `field_id` and a `scheduled_start`; the match's `scheduled_end` is computed as `scheduled_start` plus the field's `slot_minutes`, and the very first scheduling also records `original_scheduled_start`, which is preserved thereafter to order the reschedule queue. The preconditions, applied in the order of §2.9, are: both `home_team_id` and `away_team_id` must already be set (otherwise `ERR_MATCH_TEAMS_INCOMPLETE`, HTTP 409); the match must be `PENDING_TEAMS` and its division `BRACKET_PUBLISHED` (otherwise `ERR_MATCH_NOT_SCHEDULABLE`, HTTP 409); the event must be in `COMPETITION_SETUP` or `LIVE` (otherwise `ERR_EVENT_POSTURE_FORBIDS`); the field must belong to a `CONTRACTED` venue of the same event (otherwise `ERR_CROSS_EVENT_REFERENCE`, HTTP 409); the field must be `AVAILABLE` (otherwise `ERR_FIELD_BLACKED_OUT`, HTTP 409); the match's half-open window from `scheduled_start` to `scheduled_end` must not overlap the window of any other `SCHEDULED` or `IN_PROGRESS` match on the same field — half-open adjacency is allowed, so one match ending exactly when another begins is not a conflict (an overlap is `ERR_FIELD_TIME_CONFLICT`, HTTP 409); a `scheduled_start` at or after 18:00 local requires the field's `has_lights` to be true (otherwise `ERR_FIELD_NO_LIGHTS`, HTTP 409); and the scheduled date must fall within the event's `starts_on` through `ends_on` inclusive (otherwise `ERR_MATCH_OUTSIDE_EVENT_DATES`, HTTP 422). Scheduling sets `field_id` and `scheduled_start` on the match and moves it to `SCHEDULED`. The full match list supports filtering by `division_id`, `field_id`, `home_team_id`, `away_team_id`, `winner_team_id`, `winner_advances_to_match_id`, `status`, and a specific `scheduled_on` calendar date, sorting by `scheduled_start` ascending with unscheduled matches last, then `round_number` ascending, then `created_at` ascending.

### 3.6. Match Play, Weather Contingency, and the Reschedule Queue

Once the event is `LIVE`, a `CommissionAdmin` starts a `SCHEDULED` match, moving it to `IN_PROGRESS` (any other posture is `ERR_EVENT_POSTURE_FORBIDS`). Finalizing records the result: the administrator submits `home_score` and `away_score`, both of which must be zero or greater (a negative score is `ERR_SCORE_INVALID`, HTTP 422) and which must differ (a tie is `ERR_TIE_NOT_ALLOWED`, HTTP 422). The higher scorer becomes `winner_team_id` and the match becomes `FINAL`. Advancement then fires: if the match has a successor, the winner is written into the successor's home slot when the finished match's `bracket_slot` is odd, or its away slot when even, incrementing the successor match's `version`. Elimination follows the round: the loser, if `ELIGIBLE` or `CHECKED_IN`, becomes `ELIMINATED` after a non-final round or `FINISHED` after the final, while the final's winner becomes `CHAMPION`. When the last unresolved match of a division finishes, the division completes to `COMPLETED`.

A `CommissionAdmin` may instead forfeit a `SCHEDULED` or `IN_PROGRESS` match by naming the `forfeiting_team_id` and an optional `reason`; the named team must be one of the two participants (otherwise `ERR_VALIDATION`). The opponent is recorded as `winner_team_id`, and from there the advancement, elimination, and division-completion cascades are exactly those of a finalized match. Assignments on a forfeited match in `PROPOSED` or `ACCEPTED` are released with `released_reason` `MATCH_CANCELLED`.

Weather interrupts that tidy flow through alerts. A `CommissionAdmin` issues an alert with a `severity` of `WATCH`, `WARNING`, or `EMERGENCY`, a `window_start`, and a `window_end` strictly after the start (otherwise `ERR_ALERT_WINDOW_INVALID`, HTTP 422); an optional `venue_id` scopes the alert to one venue, while a null `venue_id` scopes it to every venue of the event. Creation is allowed in any non-terminal posture and the alert is born `ISSUED`; alerts of an event list by `window_start` ascending, and the filtered alert list adds `event_id`, `venue_id`, `status`, and `severity` filters with `created_at` ascending as tie-break.

Activation is the gated step: it requires `COMPETITION_SETUP` or `LIVE` posture (otherwise `ERR_EVENT_POSTURE_FORBIDS`) and moves the alert `ISSUED` → `ACTIVE`. Every match in `SCHEDULED` or `IN_PROGRESS` on a field of the scoped venues whose half-open playing window intersects the alert window becomes `WEATHER_DELAYED`, each incrementing its `version`; each such transition releases the match's assignments in `PROPOSED` or `ACCEPTED` with `released_reason` `WEATHER` and recomputes each affected official's `assigned_game_count`.

Resolving an alert has two shapes. Resolving an `ACTIVE` alert moves it to `RESOLVED` and pushes every match it delayed from `WEATHER_DELAYED` into `RESCHEDULE_QUEUE`, clearing each such match's `field_id` and `scheduled_start` — the queue holds only `original_scheduled_start` as its memory of the original plan. Resolving an alert that was never activated instead expires it, `ISSUED` → `EXPIRED`, with no match cascade at all.

The reschedule queue is drained in a strict order, and replaying a queued match requires the same inputs as scheduling — `field_id` and `scheduled_start` — with the same preconditions except that the division need only remain `BRACKET_PUBLISHED` (its status is not re-gated). A match not currently in `RESCHEDULE_QUEUE` cannot be rescheduled this way at all (`ERR_MATCH_NOT_RESCHEDULABLE`, HTTP 409). Within a division, queued matches are ordered by `round_number` ascending, then `original_scheduled_start` ascending with empty values last, then `created_at` ascending; a queued match may only be rescheduled once every other queued match of the same division that sorts earlier has already left the queue — that is, is `SCHEDULED` or in a terminal state — and jumping the queue is rejected with `ERR_RESCHEDULE_ORDER_VIOLATION` (HTTP 409). A successful reschedule updates `field_id`, `scheduled_start`, and the computed `scheduled_end`, preserves `original_scheduled_start`, and returns the match to `SCHEDULED`. The loop `SCHEDULED` → `WEATHER_DELAYED` → `RESCHEDULE_QUEUE` → `SCHEDULED` is cyclic and may repeat as often as the weather demands. Finally, matches still in `PENDING_TEAMS` when an event is cancelled move to `CANCELLED` with the event cascade of §2.5.

### 3.7. Officials and Game Assignments

Officials are registered per event by a `CommissionAdmin` with a `name`, a `certification_level` of `TRAINEE`, `REGIONAL`, or `NATIONAL`, an optional `needs_housing` flag defaulting to false that marks the official as requiring an officials-housing room booking, and an optional `game_limit_per_day` — the maximum number of accepted-or-worked games per calendar day — defaulting to 4 and at least 1. An official begins `REGISTERED`; officials of an event list by `name` ascending, filterable by `status` or `certification_level`.

The official lifecycle runs through `action` values on a transition endpoint: `VET` moves `REGISTERED` → `VETTED`; `ACTIVATE` moves `VETTED` → `ACTIVE`; `SUSPEND` moves `ACTIVE` → `SUSPENDED`; `REINSTATE` moves `SUSPENDED` → `ACTIVE`; and `DEACTIVATE` moves either `ACTIVE` or `SUSPENDED` to the terminal `INACTIVE`. Suspension is not merely clerical: suspending an `ACTIVE` official releases every one of their assignments in `PROPOSED` or `ACCEPTED` with `released_reason` `OFFICIAL_SUSPENDED` and recomputes their `assigned_game_count`, and deactivating an `ACTIVE` official applies the same release cascade; deactivating a `SUSPENDED` official has nothing left to release.

Only an `ACTIVE` official may be proposed onto a match. A `CommissionAdmin` creates an assignment by supplying the `official_id` and a `slot_role` of `CREW_CHIEF` or `ASSISTANT`, and the assignment permanently records the `match_id` it was proposed for alongside the `official_id`. The proposal is gated by a battery of checks: the official must belong to the same event as the match (otherwise `ERR_CROSS_EVENT_REFERENCE`); the match must be `SCHEDULED` (otherwise `ERR_MATCH_NOT_SCHEDULABLE`); the official must be `ACTIVE` (otherwise `ERR_OFFICIAL_NOT_ACTIVE`, HTTP 409); certification must suffice — `CREW_CHIEF` requires `REGIONAL` or `NATIONAL`, on the final round `CREW_CHIEF` requires `NATIONAL`, and a `TRAINEE` may only ever hold `ASSISTANT` (violations are `ERR_CERTIFICATION_INSUFFICIENT`, HTTP 409); the official must not already hold a non-terminal assignment on the same match, and the match must not already have a non-terminal `CREW_CHIEF` (violations are `ERR_DUPLICATE_ASSIGNMENT`, HTTP 409); and two workload limits apply. First, turnover: the candidate match's window, expanded by thirty minutes on each side, must not intersect the match window of any of that official's `ACCEPTED` or `WORKED` assignments (an intersection is `ERR_OFFICIAL_WINDOW_CONFLICT`, HTTP 409). Second, the daily cap: counting the official's `ACCEPTED` and `WORKED` assignments whose match `scheduled_start` falls on the same UTC calendar date as the candidate match, the proposal is rejected with `ERR_OFFICIAL_DAILY_LIMIT` (HTTP 409) when that count already equals or exceeds the official's `game_limit_per_day` — reaching exactly the limit is allowed, and it is the assignment that would exceed it that is refused. A created assignment begins `PROPOSED`, and the official's `assigned_game_count` — their load across assignments in `PROPOSED`, `ACCEPTED`, or `WORKED` status — increases by one.

The official then answers their own assignment, and nobody else may answer it for them: a `response` of `ACCEPTED` is legal only while the match is still `SCHEDULED` (otherwise `ERR_INVALID_STATE`) and the official still `ACTIVE` (otherwise `ERR_OFFICIAL_NOT_ACTIVE`), and acceptance adds one to `assigned_game_count`; a `response` of `DECLINED` ends the assignment and decrements the count, as the count is decremented whenever an assignment leaves the active set through release or decline. A `CommissionAdmin` may also release a `PROPOSED` or `ACCEPTED` assignment administratively, which records `released_reason` `MANUAL` and decrements the count; system cascades use `WEATHER`, `OFFICIAL_SUSPENDED`, or `MATCH_CANCELLED` as the reason instead, and `released_reason` is null on any assignment that is not `RELEASED`. After the match reaches `FINAL`, a `CommissionAdmin` marks an `ACCEPTED` assignment as worked — completing it requires the match to be `FINAL`, otherwise `ERR_INVALID_STATE` — moving it to the terminal `WORKED` status. Assignments list in `created_at` ascending order, both per match and per official.

Worked assignments are how officials are paid: at settlement time each `WORKED` assignment earns a stipend, and §3.9 defines the per-assignment amount and its rounding order.

### 3.8. Volunteers, Shifts, and Signups

Volunteer staffing starts with an application: a `CommissionAdmin` registers a volunteer under an event with a `name` and contact `email`. The volunteer begins `APPLIED` with `background_check_cleared` false; the administrator records the screening outcome by patching `background_check_cleared` on the volunteer before approval. Lifecycle actions arrive as an `action` value: `APPROVE` moves `APPLIED` → `APPROVED` but only when `background_check_cleared` is true (approving without it is rejected with `ERR_BACKGROUND_CHECK_REQUIRED`, HTTP 409); `REJECT` moves `APPLIED` to the terminal `REJECTED`; `ACTIVATE` moves `APPROVED` → `ACTIVE`; and `DEACTIVATE` moves `ACTIVE` to the terminal `INACTIVE`, cancelling that volunteer's signups in `SIGNED_UP` or `CONFIRMED` and recomputing each affected shift's `confirmed_count` — which can reopen a `FILLED` shift to `OPEN`. Volunteers list in `created_at` ascending order, filterable by `status`.

Each volunteer accumulates `hours_worked`: the sum of `credited_hours` over their signups in `WORKED` status, expressed with two decimal places; signups in any other status contribute zero.

Shifts describe the work. A `CommissionAdmin` creates a shift under an event with a `role_needed` of `FIELD_MARSHAL`, `REGISTRATION_DESK`, `SCORE_RUNNER`, `HOSPITALITY`, or `PARKING`, a `starts_at`, an `ends_at` strictly after the start (otherwise `ERR_SHIFT_TIME_INVALID`, HTTP 422), and a `capacity` of at least 1 — the maximum number of confirmed signups. A shift opens `OPEN`, and its `confirmed_count` tracks its signups in `CONFIRMED` or `WORKED`. Shifts list by `starts_at` ascending then `created_at` ascending, filterable by `status` or `role_needed`. The `OPEN` ↔ `FILLED` pair is a self-managing bubble: when `confirmed_count` reaches `capacity` the shift becomes `FILLED` on its own, and when a cancellation or no-show later drops the count below `capacity` it reopens to `OPEN`.

Signing up creates the link. A `CommissionAdmin`, or a `Volunteer` acting for themselves, signs a volunteer into a shift by supplying `volunteer_id`. The volunteer must be `ACTIVE` (otherwise `ERR_INVALID_STATE`), must belong to the same event as the shift (otherwise `ERR_CROSS_EVENT_REFERENCE`), and the shift must be `OPEN` (otherwise `ERR_SHIFT_NOT_OPEN`, HTTP 409). Capacity bites at two depths: the shift's count of non-cancelled signups must be below `capacity` to accept a new signup at all, and later confirmation must find `confirmed_count` below `capacity` — either failure is `ERR_SHIFT_FULL` (HTTP 409). Finally, the volunteer's existing `SIGNED_UP` and `CONFIRMED` signups must have pairwise non-overlapping half-open shift windows from `starts_at` to `ends_at`; an overlapping commitment is rejected with `ERR_SHIFT_WINDOW_OVERLAP` (HTTP 409). A new signup begins `SIGNED_UP`, recording the `shift_id` it belongs to and the signing `volunteer_id`, and signups list in `created_at` ascending order both per shift and per volunteer.

Confirmation moves `SIGNED_UP` → `CONFIRMED`, is performed by a `CommissionAdmin`, requires the shift to be `OPEN` or `FILLED` (otherwise `ERR_SHIFT_NOT_OPEN`) with `confirmed_count` still below `capacity` (otherwise `ERR_SHIFT_FULL`), and increments `confirmed_count` by one — which may bubble the shift to `FILLED`. Cancelling a signup, available to a `CommissionAdmin` or the signup's own `Volunteer`, moves `SIGNED_UP` or `CONFIRMED` to `CANCELLED`; cancelling a `CONFIRMED` signup decrements `confirmed_count` and may reopen a `FILLED` shift. Marking a `CONFIRMED` signup `NO_SHOW` is a `CommissionAdmin` action legal only once the logical clock has passed the shift's `ends_at` (otherwise `ERR_SHIFT_TIME_INVALID`), and it likewise decrements `confirmed_count` and may reopen the shift.

After a shift's window has passed — the logical clock strictly past `ends_at`, otherwise `ERR_SHIFT_TIME_INVALID` — a `CommissionAdmin` completes the shift, moving it to `COMPLETED`. Completion resolves every remaining signup: each `CONFIRMED` signup becomes `WORKED` and earns `credited_hours` equal to the shift's duration — the difference between `ends_at` and `starts_at` in minutes, divided by sixty, rounded half up to two decimal places — while each signup still `SIGNED_UP` is cancelled; every volunteer's `hours_worked` is then recomputed. Cancelling the shift outright, from `OPEN` or `FILLED`, instead moves it to `CANCELLED` and cancels every signup in `SIGNED_UP` or `CONFIRMED` without credit.

### 3.9. Economic Impact Reporting and Settlement

Once the event reaches `COMPLETED`, attention turns to the money. A `CommissionAdmin` creates an economic impact report for the event — the posture gate rejects creation earlier with `ERR_EVENT_POSTURE_FORBIDS` — supplying `projected_attendance`, the projected count of unique attendees (zero or more), and optional `notes`. The report is born `DRAFT` with `created_by_user_id` stamped from the creator's `X-User-ID`, and reports list in `created_at` ascending order with an optional `status` filter.

Submitting the report snapshots the projected variant of the direct-spend calculation. `projected_room_nights` becomes the sum of `room_nights` over the event's bookings in `RESERVED`, `CONFIRMED`, `CHECKED_IN`, `CHECKED_OUT`, or `NO_SHOW` status, and `projected_direct_spend_cents` becomes the sum of those bookings' `total_charge_cents` plus 14,500 cents — that is, $145.00 of per-capita spending — for every projected attendee. No intermediate rounding applies; everything is integer cents.

Audit is the bureau's turn. A `CvbAuditor` whose `X-User-ID` differs from the report's `created_by_user_id` (per §2.11, otherwise `ERR_SOD_VIOLATION`) posts the audited figures by supplying `actual_attendance` — the audited attendance count, zero or more, null until this moment — moving the report `SUBMITTED` → `UNDER_AUDIT`, stamping `audited_by_user_id`, and computing the audited variant: `actual_room_nights` sums `room_nights` over only the event's `CHECKED_OUT` and `NO_SHOW` bookings, and `audited_direct_spend_cents` (also null until audit) sums those bookings' `total_charge_cents` plus the same 14,500 cents per actual attendee. Identical event data therefore produces a different audited total than the projected one, because the booking set and the attendance figure both change. The auditor then renders an audit `decision`: `ACCEPTED` moves the report to its terminal `ACCEPTED` status, while `DISPUTED` sends it to `DISPUTED`. A disputed report returns to `DRAFT` through a revision by a `CommissionAdmin`, incrementing `revision_count` — which counts exactly those `DISPUTED` → `DRAFT` cycles — so the loop `DRAFT` → `SUBMITTED` → `UNDER_AUDIT` → `DISPUTED` → `DRAFT` can repeat until the bureau accepts.

Settlement is the final accounting, and an event has at most one: creating a second settlement for the same event is rejected with `ERR_SETTLEMENT_EXISTS` (HTTP 409), and creating the first requires `COMPLETED` posture. A `CommissionAdmin` creates it with `sponsor_contributions_cents` — the sponsor and CVB contributions recognized in the settlement, zero or more — and it opens in `OPEN` status with an empty `expense_lines` list. While the settlement is `OPEN`, the administrator appends expense entries, each with a `category`, an `amount_cents`, and a `description`; `expense_total_cents` is the running sum of those amounts, and the list becomes immutable once the settlement leaves `OPEN`.

Certification freezes the books. A `CommissionAdmin` certifies an `OPEN` settlement only when every hotel block of the event is in `RECONCILED`, `SETTLED`, or `RELEASED` (otherwise `ERR_BLOCK_NOT_RECONCILABLE`, HTTP 409). Certification stamps `certified_by_user_id` and snapshots every computed total in one atomic act:

- `registration_revenue_cents`: the sum, over every team of the event in a fee-paid status — `ROSTER_SUBMITTED`, `ELIGIBLE`, `CHECKED_IN`, `ELIMINATED`, `FINISHED`, `CHAMPION`, or `DISQUALIFIED` — of that team's division's `registration_fee_cents`. `ENTERED`, `WAITLISTED`, and `WITHDRAWN` teams are excluded, their fee not yet due or refunded.
- `rebate_total_cents`: the sum of `final_rebate_cents` over the event's `RECONCILED` and `SETTLED` hotel blocks.
- `sanction_fee_cents`: the sanctioning body's marginal tiered fee on `registration_revenue_cents` — the first 5,000,000 cents ($50,000) at 8%, the next 5,000,000 cents (the portion from 5,000,001 through 10,000,000 cents) at 10%, and any remainder above 10,000,000 cents ($100,000) at 12%. Each tier's slice is rounded half up to whole cents first and the rounded slices are then summed; rounding once on the total is non-conformant.
- `venue_rental_total_cents`: the sum of `rental_fee_cents` over the event's `CONTRACTED` and `RELEASED` venues.
- `officials_stipend_total_cents`: the sum over the event's `WORKED` assignments of a per-assignment stipend — 9,999 cents ($99.99) multiplied by the official's certification multiplier, 0.6 for `TRAINEE`, 1.0 for `REGIONAL`, and 1.5 for `NATIONAL` — with each assignment's stipend rounded half up to whole cents before summation. Summing the raw products and rounding once yields a different total and is non-conformant.
- `expense_total_cents`: the sum of the appended expense line amounts.
- `gross_revenue_cents`: `registration_revenue_cents` plus `rebate_total_cents` plus `sponsor_contributions_cents`.
- `net_to_commission_cents`: the waterfall remainder. Deductions apply in a strict bucket order — the sanction fee first, then venue rental, then officials' stipends, then the expense total — each bucket fully satisfied before the next, and the remainder after all four deductions is the net. The net may be negative, in which case it represents a receivable: the commission owes the difference.

Approval is segregated: a `CommissionAdmin` approves an `EXPENSES_CERTIFIED` settlement only if their `X-User-ID` differs from `certified_by_user_id` (otherwise `ERR_SOD_VIOLATION`) and an impact report of the event has reached `ACCEPTED` (otherwise `ERR_IMPACT_REPORT_NOT_ACCEPTED`, HTTP 409). Approval stamps `approved_by_user_id`. Payment then moves `APPROVED` → `PAID` and fires the closing cascade of §2.5: the event moves `COMPLETED` → `SETTLED`, and every hotel block still `RECONCILED` becomes `SETTLED` with its `final_rebate_cents` and `attrition_penalty_cents` frozen.

The settlement also has a dispute loop for when the numbers are challenged. A `CommissionAdmin` or a `CvbAuditor` may dispute an `EXPENSES_CERTIFIED` settlement by supplying a `dispute_reason`, moving it to `DISPUTED`. A `CommissionAdmin` may then reopen a `DISPUTED` settlement, returning it to `OPEN`, clearing `certified_by_user_id`, and making `expense_lines` editable again — so the cycle `OPEN` → `EXPENSES_CERTIFIED` → `DISPUTED` → `OPEN` can repeat until certification, approval, and payment finally close the event. Settlements list in `created_at` ascending order, and since an event has at most one, that list holds zero or one row.

## 4. Endpoint Definitions

Operations that create a new resource — an event, a bid, a requirement, a venue, a field, a hotel block, a booking, a division, a team, an official, a volunteer, a shift, a signup, a weather alert, an impact report, a settlement, or an assignment proposal — return `201 Created`. Operations that modify an existing resource, including all lifecycle transitions, posture advances, edits, and decisions, return `200 OK`; the logical-clock setter also returns `200 OK`. The table below is a navigational index only: request payloads, response shapes, preconditions, and side effects are defined by the narratives in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/v1/_clock/set_current_utc` | Set the server's logical clock | CommissionAdmin |
| POST | `/api/v1/events` | Create an event (posture `BIDDING`) | CommissionAdmin |
| GET | `/api/v1/events` | List events | Any |
| GET | `/api/v1/events/{id}` | Get one event | Any |
| POST | `/api/v1/events/{id}/posture` | Advance event posture | CommissionAdmin |
| GET | `/api/v1/events/{id}/summary` | Computed operational summary | Any |
| POST | `/api/v1/events/{id}/bids` | Create a bid (renewal-aware) | CommissionAdmin |
| GET | `/api/v1/events/{id}/bids` | List bids of an event | Any |
| GET | `/api/v1/bids/{id}` | Get one bid | Any |
| PATCH | `/api/v1/bids/{id}` | Edit bid notes while editable | CommissionAdmin |
| POST | `/api/v1/bids/{id}/submit` | Submit bid | CommissionAdmin |
| POST | `/api/v1/bids/{id}/withdraw` | Withdraw a bid | CommissionAdmin |
| POST | `/api/v1/bids/{id}/review` | Open sanctioning review | SanctioningReviewer |
| POST | `/api/v1/bids/{id}/request-revision` | Request bid revisions | SanctioningReviewer |
| POST | `/api/v1/bids/{id}/decide` | Award or reject a bid | SanctioningReviewer |
| GET | `/api/v1/bids/{id}/requirements` | List requirements of a bid | Any |
| POST | `/api/v1/bids/{id}/requirements` | Add a checklist requirement | CommissionAdmin |
| GET | `/api/v1/requirements/{id}` | Get one requirement | Any |
| POST | `/api/v1/requirements/{id}/evidence` | Submit requirement evidence | CommissionAdmin |
| POST | `/api/v1/requirements/{id}/verify` | Verify or return evidence | SanctioningReviewer |
| POST | `/api/v1/requirements/{id}/waive` | Waive a non-mandatory requirement | SanctioningReviewer |
| POST | `/api/v1/events/{id}/venues` | Create a venue | CommissionAdmin |
| GET | `/api/v1/events/{id}/venues` | List venues of an event | Any |
| GET | `/api/v1/venues/{id}` | Get one venue | Any |
| POST | `/api/v1/venues/{id}/contract` | Execute venue agreement | CommissionAdmin |
| POST | `/api/v1/venues/{id}/release` | Release a venue | CommissionAdmin |
| POST | `/api/v1/venues/{id}/fields` | Create a field on a venue | CommissionAdmin, VenueManager |
| GET | `/api/v1/venues/{id}/fields` | List fields of a venue | Any |
| GET | `/api/v1/fields/{id}` | Get one field | Any |
| POST | `/api/v1/fields/{id}/blackout` | Black out a field for a window | CommissionAdmin, VenueManager |
| POST | `/api/v1/fields/{id}/unblackout` | Clear a field blackout | CommissionAdmin, VenueManager |
| GET | `/api/v1/fields/{id}/matches` | List matches scheduled on a field | Any |
| POST | `/api/v1/events/{id}/hotel-blocks` | Create a hotel block | CommissionAdmin |
| GET | `/api/v1/events/{id}/hotel-blocks` | List hotel blocks of an event | Any |
| GET | `/api/v1/hotel-blocks/{id}` | Get one hotel block | Any |
| PATCH | `/api/v1/hotel-blocks/{id}` | Edit negotiating block terms | CommissionAdmin |
| POST | `/api/v1/hotel-blocks/{id}/contract` | Execute block agreement | CommissionAdmin |
| POST | `/api/v1/hotel-blocks/{id}/close-cutoff` | Close the booking window | CommissionAdmin |
| POST | `/api/v1/hotel-blocks/{id}/reconcile` | Reconcile pickup and rebate | CommissionAdmin, HotelManager |
| GET | `/api/v1/hotel-blocks/{id}/room-bookings` | List bookings of a block | Any |
| POST | `/api/v1/hotel-blocks/{id}/room-bookings` | Create a room booking | CommissionAdmin, TeamRep, Official |
| GET | `/api/v1/room-bookings/{id}` | Get one booking | Any |
| GET | `/api/v1/room-bookings` | Filtered booking list | Any |
| POST | `/api/v1/room-bookings/{id}/transition` | Booking lifecycle action | CommissionAdmin, HotelManager, TeamRep, Official |
| POST | `/api/v1/events/{id}/divisions` | Create a division | CommissionAdmin |
| GET | `/api/v1/events/{id}/divisions` | List divisions of an event | Any |
| GET | `/api/v1/divisions/{id}` | Get one division | Any |
| POST | `/api/v1/divisions/{id}/lock-seeding` | Lock seeding and assign seeds | CommissionAdmin |
| POST | `/api/v1/divisions/{id}/publish-bracket` | Generate bracket matches | CommissionAdmin |
| GET | `/api/v1/divisions/{id}/teams` | List teams of a division | Any |
| GET | `/api/v1/divisions/{id}/matches` | List matches of a division | Any |
| POST | `/api/v1/divisions/{id}/teams` | Register a team | CommissionAdmin |
| GET | `/api/v1/teams/{id}` | Get one team | Any |
| POST | `/api/v1/teams/{id}/roster` | Submit team roster | TeamRep |
| POST | `/api/v1/teams/{id}/verify-eligibility` | Mark team eligible | CommissionAdmin |
| POST | `/api/v1/teams/{id}/check-in` | Event-day team check-in | CommissionAdmin, TeamRep |
| POST | `/api/v1/teams/{id}/withdraw` | Withdraw a team | CommissionAdmin, TeamRep |
| POST | `/api/v1/teams/{id}/disqualify` | Disqualify a team | CommissionAdmin |

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| GET | `/api/v1/matches/{id}` | Get one match | Any |
| GET | `/api/v1/matches` | Filtered match list | Any |
| POST | `/api/v1/matches/{id}/schedule` | Schedule a pending match onto a field | CommissionAdmin |
| POST | `/api/v1/matches/{id}/reschedule` | Reschedule a queued match in queue order | CommissionAdmin |
| POST | `/api/v1/matches/{id}/start` | Start a scheduled match | CommissionAdmin |
| POST | `/api/v1/matches/{id}/finalize` | Record the final score | CommissionAdmin |
| POST | `/api/v1/matches/{id}/forfeit` | Forfeit a match | CommissionAdmin |
| GET | `/api/v1/matches/{id}/official-assignments` | List assignments of a match | Any |
| POST | `/api/v1/events/{id}/officials` | Register an official | CommissionAdmin |
| GET | `/api/v1/events/{id}/officials` | List officials of an event | Any |
| GET | `/api/v1/officials/{id}` | Get one official | Any |
| POST | `/api/v1/officials/{id}/transition` | Official lifecycle action | CommissionAdmin |
| GET | `/api/v1/officials/{id}/assignments` | List assignments of an official | Any |
| POST | `/api/v1/matches/{id}/official-assignments` | Propose an official for a match | CommissionAdmin |
| GET | `/api/v1/official-assignments/{id}` | Get one assignment | Any |
| POST | `/api/v1/official-assignments/{id}/respond` | Official accepts or declines | Official |
| POST | `/api/v1/official-assignments/{id}/release` | Administratively release an assignment | CommissionAdmin |
| POST | `/api/v1/official-assignments/{id}/complete` | Mark an assignment worked | CommissionAdmin |
| POST | `/api/v1/events/{id}/volunteers` | Volunteer application | CommissionAdmin |
| GET | `/api/v1/events/{id}/volunteers` | List volunteers of an event | Any |
| GET | `/api/v1/volunteers/{id}` | Get one volunteer | Any |
| PATCH | `/api/v1/volunteers/{id}` | Set background-check clearance | CommissionAdmin |
| POST | `/api/v1/volunteers/{id}/transition` | Volunteer lifecycle action | CommissionAdmin |
| GET | `/api/v1/volunteers/{id}/signups` | List signups of a volunteer | Any |
| POST | `/api/v1/events/{id}/shifts` | Create a volunteer shift | CommissionAdmin |
| GET | `/api/v1/events/{id}/shifts` | List shifts of an event | Any |
| GET | `/api/v1/shifts/{id}` | Get one shift | Any |
| POST | `/api/v1/shifts/{id}/cancel` | Cancel a shift | CommissionAdmin |
| POST | `/api/v1/shifts/{id}/complete` | Complete a shift after its window | CommissionAdmin |
| GET | `/api/v1/shifts/{id}/signups` | List signups of a shift | Any |
| POST | `/api/v1/shifts/{id}/signups` | Sign a volunteer up | CommissionAdmin, Volunteer |
| GET | `/api/v1/shift-signups/{id}` | Get one signup | Any |
| POST | `/api/v1/shift-signups/{id}/confirm` | Confirm a signup | CommissionAdmin |
| POST | `/api/v1/shift-signups/{id}/cancel` | Cancel a signup | CommissionAdmin, Volunteer |
| POST | `/api/v1/shift-signups/{id}/mark-no-show` | Mark a confirmed signup no-show | CommissionAdmin |
| POST | `/api/v1/events/{id}/weather-alerts` | Issue a weather alert | CommissionAdmin |
| GET | `/api/v1/events/{id}/weather-alerts` | List weather alerts of an event | Any |
| GET | `/api/v1/weather-alerts/{id}` | Get one weather alert | Any |
| GET | `/api/v1/weather-alerts` | Filtered weather alert list | Any |
| POST | `/api/v1/weather-alerts/{id}/activate` | Activate an alert and delay matches | CommissionAdmin |
| POST | `/api/v1/weather-alerts/{id}/resolve` | Resolve or expire an alert | CommissionAdmin |
| POST | `/api/v1/events/{id}/impact-reports` | Create an impact report | CommissionAdmin |
| GET | `/api/v1/events/{id}/impact-reports` | List impact reports of an event | Any |
| GET | `/api/v1/impact-reports/{id}` | Get one impact report | Any |
| POST | `/api/v1/impact-reports/{id}/submit` | Submit the report | CommissionAdmin |
| POST | `/api/v1/impact-reports/{id}/audit` | Auditor posts actuals | CvbAuditor |
| POST | `/api/v1/impact-reports/{id}/audit-decision` | Accept or dispute the audit | CvbAuditor |
| POST | `/api/v1/impact-reports/{id}/revise` | Return a disputed report to draft | CommissionAdmin |
| POST | `/api/v1/events/{id}/settlements` | Create the event settlement | CommissionAdmin |
| GET | `/api/v1/events/{id}/settlements` | List settlements of an event | Any |
| GET | `/api/v1/settlements/{id}` | Get one settlement | Any |
| POST | `/api/v1/settlements/{id}/expense-lines` | Append an expense line | CommissionAdmin |
| POST | `/api/v1/settlements/{id}/certify` | Certify expenses and snapshot totals | CommissionAdmin |
| POST | `/api/v1/settlements/{id}/approve` | Approve the settlement | CommissionAdmin |
| POST | `/api/v1/settlements/{id}/pay` | Pay out and settle the event | CommissionAdmin |
| POST | `/api/v1/settlements/{id}/dispute` | Dispute a certified settlement | CommissionAdmin, CvbAuditor |
| POST | `/api/v1/settlements/{id}/reopen` | Reopen a disputed settlement | CommissionAdmin |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. Trigger conditions are defined where each rule lives in §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_EVENT_POSTURE_FORBIDS` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_BID_NOT_EDITABLE` | 409 Conflict |
| `ERR_BID_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_BID_REQUIREMENTS_INCOMPLETE` | 409 Conflict |
| `ERR_BID_SCORE_BELOW_THRESHOLD` | 409 Conflict |
| `ERR_REQUIREMENT_NOT_WAIVABLE` | 409 Conflict |
| `ERR_REQUIREMENT_NOT_REVIEWABLE` | 409 Conflict |
| `ERR_DIVISION_NOT_OPEN` | 409 Conflict |
| `ERR_DIVISION_BELOW_MIN_TEAMS` | 409 Conflict |
| `ERR_ROSTER_TOO_SMALL` | 422 Unprocessable Entity |
| `ERR_MATCH_TEAMS_INCOMPLETE` | 409 Conflict |
| `ERR_MATCH_NOT_SCHEDULABLE` | 409 Conflict |
| `ERR_MATCH_NOT_RESCHEDULABLE` | 409 Conflict |
| `ERR_RESCHEDULE_ORDER_VIOLATION` | 409 Conflict |
| `ERR_TIE_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_SCORE_INVALID` | 422 Unprocessable Entity |
| `ERR_FIELD_TIME_CONFLICT` | 409 Conflict |
| `ERR_FIELD_BLACKED_OUT` | 409 Conflict |
| `ERR_FIELD_NO_LIGHTS` | 409 Conflict |
| `ERR_MATCH_OUTSIDE_EVENT_DATES` | 422 Unprocessable Entity |
| `ERR_OFFICIAL_NOT_ACTIVE` | 409 Conflict |
| `ERR_CERTIFICATION_INSUFFICIENT` | 409 Conflict |
| `ERR_OFFICIAL_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_OFFICIAL_DAILY_LIMIT` | 409 Conflict |
| `ERR_DUPLICATE_ASSIGNMENT` | 409 Conflict |
| `ERR_BLOCK_NOT_CONTRACTED` | 409 Conflict |
| `ERR_BLOCK_NOT_RECONCILABLE` | 409 Conflict |
| `ERR_BLOCK_INVENTORY_EXCEEDED` | 409 Conflict |
| `ERR_BOOKING_OUTSIDE_BLOCK_DATES` | 422 Unprocessable Entity |
| `ERR_CUTOFF_PASSED` | 409 Conflict |
| `ERR_BACKGROUND_CHECK_REQUIRED` | 409 Conflict |
| `ERR_SHIFT_NOT_OPEN` | 409 Conflict |
| `ERR_SHIFT_FULL` | 409 Conflict |
| `ERR_SHIFT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_SHIFT_TIME_INVALID` | 422 Unprocessable Entity |
| `ERR_CROSS_EVENT_REFERENCE` | 409 Conflict |
| `ERR_VENUE_HAS_ACTIVE_MATCHES` | 409 Conflict |
| `ERR_SETTLEMENT_EXISTS` | 409 Conflict |
| `ERR_IMPACT_REPORT_NOT_ACCEPTED` | 409 Conflict |
| `ERR_ALERT_WINDOW_INVALID` | 422 Unprocessable Entity |









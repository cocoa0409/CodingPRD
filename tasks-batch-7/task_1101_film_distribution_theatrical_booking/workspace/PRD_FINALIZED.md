# Film Distribution & Theatrical Booking API — Product Requirements Document

## 1. Introduction

An independent film distributor lives and dies by a calendar of negotiated commitments: which theatres play which picture, on how many screens, for how many weeks, and at what rental split. The work is a continuous multi-party negotiation — bookers haggle with exhibitor circuits over weekly rental percentages and per-capita floors, prints and keys must physically arrive before a playdate can go live, box office grosses are reported nightly and settled weekly, and every dispute over money or exclusivity ripples across the entire slate. This document specifies an API that manages that operational surface for a distributor: release strategy and screen-count gates, exhibitor booking agreements with cyclic counter-offer negotiation, aggregate circuit-level deals, DCP shipment and KDM key logistics, box office reporting and weekly settlement, holdover decisions and screen reallocation, marketing co-op commitments, zone-clearance disputes, and the final handoff to ancillary windows.

Two design commitments shape everything that follows. First, the system treats money as a ledger to be reconciled rather than a number to be estimated: every settlement exists in a forward-looking provisional form and a locked final form, and the transition between the two is driven by a deterministic weekly close. Second, the platform runs on a logical clock rather than wall-clock time, so that key expirations, zone expirations, playdate activation, and ancillary handoffs are reproducible and testable. Roles are strictly segregated — the operator who negotiates a deal is never the operator who settles its money — and writers on the negotiation surface are protected by optimistic concurrency.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that hold for every endpoint in the system.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which that user acts. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the named role is not permitted to perform the requested operation, the request is rejected with `ERR_ROLE_FORBIDDEN` (HTTP 403).

The system recognizes exactly six roles, spelled as follows: `PlatformAdmin`, `Booker`, `Exhibitor`, `SettlementClerk`, `MarketingLead`, and `Auditor`. A `PlatformAdmin` provisions infrastructure — distributors, markets, theatres, screens — and alone may advance the logical clock. A `Booker` is the distributor's negotiator: they register films, propose and counter booking terms, manage aggregate deals, shipments, keys, zone clearances, holdover decisions, and ancillary scheduling. An `Exhibitor` is the theatre-circuit counterparty: they counter or accept terms, confirm delivery of content, file box office reports, dispute settlements, and challenge clearances. A `SettlementClerk` runs the weekly close and settles money, subject to the segregation-of-duties rule in §3.7. A `MarketingLead` manages co-op marketing commitments within a market. An `Auditor` holds read-only access.

For all six roles — `PlatformAdmin`, `Booker`, `Exhibitor`, `SettlementClerk`, `MarketingLead`, and `Auditor` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, when evaluating segregation of duties against the creator of a `BookingAgreement`, or when checking that a zone-clearance challenger differs from the granted theatre) but it never compares `X-User-ID` to any entity's `id`. All roles share read-only access to every resource through the list and read endpoints enumerated in §4.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

Most collections additionally accept optional equality filters drawn from the resource's own fields: `lifecycle_status`, `release_pattern`, `distributor_id`, `market_code`, `circuit`, `status`, `film_id`, `theatre_id`, `screen_id`, `aggregate_deal_id`, `deal_status`, `print_status`, `booking_agreement_id`, `week_index`, `variant`, `decision`, `market_id`, `parent_dispute_id`, and `window_kind`, as applicable per collection in §4.

### 2.4. Common Resource Properties

Every resource in the system — Distributor, Film, Theatre, Screen, Market, BookingAgreement, AggregateDeal, DCPShipment, KDMKey, BoxOfficeReport, Settlement, HoldoverDecision, MarketingCommitment, ZoneClearance, and AncillaryWindow — carries the same four system-managed properties, with no exceptions:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits (for example, `2026-05-01T00:00:00.000Z`), set when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that increments on every mutation of the resource, including mutations driven by automatic cascades such as weekly closes, clock advancements, and parent-side reconciliation.

Independently of any business rule, a request whose payload is malformed, missing a required field, or carrying an invalid enum value is rejected with `ERR_INVALID_REQUEST` (HTTP 400) before business validation begins.

### 2.5. The Logical Clock and the Box-Office Week

Two timekeeping primitives govern all temporal behavior. The first is `logical_clock_utc`, a single global logical clock shared by every distributor. At server startup it reads exactly `2026-05-01T00:00:00Z`; before any clock call has been made it must hold this default and must never fall back to wall-clock time. The clock advances only when a `PlatformAdmin` invokes the clock capability with a target instant supplied as `to_iso8601`; the new value applies to all distributors at once. Clock advancement is the driver of every automatic time-based transition: KDM keys going live at the start of their validity window and expiring at its end, zone clearances expiring past their window, accepted bookings entering play once their opening date arrives with a live key, films completing the ancillary handoff once the theatrical window ends, and scheduled ancillary windows handing off.

The second primitive is `week_epoch`, a per-distributor monotone counter that starts at 0 and advances by exactly one each time a `SettlementClerk` closes the box-office week. The weekly close is the system's reconciliation checkpoint: it locks submitted reports, finalizes settlements, computes holdover recommendations, completes finished agreements, and sweeps expired clearances, keys, and violated windows. The full cascade is specified in §3.6.

### 2.6. Nested Resource Retrieval

All resources live beneath a distributor, and most live several levels deep. When an endpoint path contains multiple resource identifiers, the server validates them left to right: each identifier must resolve to an existing resource within the scope established by the identifiers to its left, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that fails to resolve. A shipment addressed under the wrong booking agreement, or a screen addressed under the wrong theatre, is therefore a 404 at the mismatched segment, never a business-rule error. The path parameters used throughout the API are `did` (distributor), `fid` (film), `mid` (market), `tid` (theatre), `sid` (screen, shipment, or settlement, per position), `aid` (aggregate deal), `baid` (booking agreement), `rid` (box office report), `kid` (KDM key), `mcid` (marketing commitment), `zid` (zone clearance), and `awid` (ancillary window); some routes use a generic `id` placeholder for the final segment.

### 2.7. Optimistic Concurrency Control

Three write operations require the caller to present the version of the parent resource it last observed, and reject the write when that view is stale:

- A counter-offer on a booking agreement must carry `expected_booking_agreement_version`, equal to the agreement's current `version` as the client last read it. If the agreement's version has since advanced — because another writer countered, accepted, or otherwise mutated it — the counter-offer is rejected with `ERR_STALE_VERSION` (HTTP 412).
- An acceptance of a booking agreement carries the same `expected_booking_agreement_version` requirement and the same `ERR_STALE_VERSION` (HTTP 412) rejection on mismatch; the client must re-read the agreement and observe the latest negotiated terms before accepting.
- Opening a film's release must carry `expected_film_version`, matching the film's current `version`. Because every booking acceptance advances the film's committed-screen count and version, a release decision made from a stale read is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the booker to re-read the film before judging whether the wide-release gate is met.

Endpoints not named above do not take a version field of any kind.

### 2.8. Money, Percentages, and Precision

All monetary amounts are integer cents — `gross_cents`, `house_allowance_cents`, `net_cents`, `distributor_share_cents`, `exhibitor_share_cents`, `marketing_offset_cents`, `final_distributor_payout_cents`, `committed_cents`, `spent_cents`, `outstanding_cents`, `weekly_coop_budget_cents`, `coop_committed_cents`, `per_capita_floor_cents`, `aggregate_house_allowance_cents`, and `prior_week_gross_cents` are all whole-cent integers; no fractional cents exist anywhere in the system.

Rental percentages — `week_one_rental_pct`, `rental_decay_per_week`, `floor_pct`, `aggregate_rental_pct`, `rental_pct_applied`, and the derived `current_week_rental_pct` — are carried to exactly 4 decimal places using round-half-up, and admissible input percentages lie between 0.00 and 0.95 inclusive. Within the settlement calculation, the single rounding event is the multiplication of net cents by the applied percentage, which rounds half-up to whole cents; every subsequent step uses exact integer arithmetic with no further rounding.

### 2.9. Closed Windows versus Half-Open Windows

The system deliberately uses two different interval semantics, and confusing them is the classic integration bug.

Zone clearances use a **closed interval**: both `effective_from_utc` and `effective_until_utc` are inclusive. Two clearance windows overlap whenever the first window's start is on or before the second window's end and the second window's start is on or before the first window's end. Because both ends are inclusive, pure adjacency is a conflict: a window ending at exactly the instant another begins overlaps it. A clearance remains in force at exactly its `effective_until_utc` and expires only once the logical clock has moved strictly past that instant.

KDM validity windows use a **half-open interval**: `valid_from_utc` is inclusive and `valid_until_utc` is exclusive. A key is live at an instant that is on or after its start and strictly before its end; at exactly `valid_until_utc` the key is expired, not live. Two key windows on the same screen conflict only when each window's start is strictly before the other window's end; adjacency — one key ending at exactly the instant the next begins — is not a conflict. This contrast with the zone-clearance rule is intentional and both behaviors are specified.

### 2.10. Hierarchical Consistency and Cascading Mutation

Acceptance, completion, cancellation, dispute, and resolution are never single-resource events. Accepting a booking books its screen and increments the film's committed-screen count; completing or cancelling a booking frees the screen and decrements that count; disputing a settlement freezes the distributor's posture and resolving the last open dispute restores it. Each such cascade mutates every resource it touches: the resource's own fields change, its `updated_at` refreshes, and its `version` increments. The server may perform these reconciliations automatically, without an explicit client request on the affected resource, whenever the governing criteria in §3 are met.

### 2.11. Validation Precedence

Where several guards apply to one operation, they are evaluated in a fixed global order, and the first failing guard produces the error:

1. Authentication — headers present and well-formed (`ERR_UNAUTHENTICATED`).
2. Role authorization — the role may call this endpoint (`ERR_ROLE_FORBIDDEN`).
3. Path existence, left to right (`ERR_NOT_FOUND`).
4. Distributor posture — a `FROZEN` distributor blocks new booking creation, counter-offers, and acceptances (`ERR_DISTRIBUTOR_FROZEN`).
5. State-machine validity — the resource is in a state from which the requested transition exists (`ERR_INVALID_STATE`).
6. Film bookability — the film's lifecycle permits booking (`ERR_FILM_NOT_BOOKABLE`).
7. KDM window conflict on the same screen (`ERR_KDM_WINDOW_CONFLICT`).
8. Print readiness — the print axis permits key issuance (`ERR_PRINT_NOT_READY`).
9. Zone clearance conflict (`ERR_ZONE_CLEARANCE_CONFLICT`).
10. Ancillary scheduling earliness (`ERR_ANCILLARY_TOO_EARLY`).
11. Referential integrity of supplied foreign keys (`ERR_REFERENTIAL_INTEGRITY`).
12. Screen–theatre match (`ERR_SCREEN_THEATRE_MISMATCH`).
13. Screen availability (`ERR_SCREEN_UNAVAILABLE`).
14. Wide-release gate (`ERR_WIDE_GATE_NOT_MET`).
15. Co-op budget cap (`ERR_COOP_BUDGET_EXCEEDED`).
16. Rental-term validity (`ERR_INVALID_RENTAL_TERMS`).
17. Segregation of duties (`ERR_SOD_VIOLATION`).
18. Holdover eligibility (`ERR_HOLDOVER_NOT_ELIGIBLE`).
19. Report date window (`ERR_REPORT_OUTSIDE_WINDOW`).
20. Optimistic concurrency (`ERR_STALE_VERSION`), checked last.

Two consequences are worth stating plainly. A counter-offer sent to a frozen distributor fails with `ERR_DISTRIBUTOR_FROZEN` even when the supplied version is also stale, because posture outranks the concurrency check; and on booking creation the referential, screen–theatre, and screen-availability checks are all resolved before the rental terms themselves are examined.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Distribution Operation

A `PlatformAdmin` begins by creating the Distributor itself, supplying its legal `name` and its `territory` as an ISO country or territory code such as US. A new distributor starts with `week_epoch` at 0, a `lifecycle_posture` of `ACTIVE`, and the shared logical clock at its startup default. The posture is a computed field: the distributor is `FROZEN` whenever any settlement anywhere in its tree stands in `DISPUTED`, and returns to `ACTIVE` when the last such dispute resolves; while `FROZEN`, no new booking agreements can be created, countered, or accepted.

Markets come next. Each market is registered under a short DMA `code` such as NYC, LA, or CHI, a `population_tier` of `TIER_1`, `TIER_2`, or `TIER_3`, and a `weekly_coop_budget_cents` expressing the distributor's per-week marketing co-op budget for that market. The market's `coop_committed_cents` — the running total of co-op money committed against it — starts at 0 and is maintained by the commitment lifecycle in §3.9.

Theatres belong to the distributor and serve a market. Creating one takes a `name`, a `circuit` identifier such as Alamo, Landmark, or Independent, the `market_code` of the market it serves, and a `house_allowance_cents` — the fixed weekly house expense deducted from gross before the rental split. A theatre is created `ACTIVE`; a `PlatformAdmin` may suspend it, moving it to `SUSPENDED`, which blocks new bookings from being accepted at that theatre until it is restored; `DARK` records a theatre that has ceased operation. Screens are created within a theatre with an `auditorium_label` such as "Auditorium 3", a `seat_count`, and a `projection_format` of `DCP_2K`, `DCP_4K`, or `FILM_35MM`. A screen starts `AVAILABLE`, becomes `BOOKED` while committed to a live agreement, and may be parked in `MAINTENANCE`.

### 3.2. Registering Films and Choosing a Release Strategy

A `Booker` registers a film with a `title`, a `genre` of `NARRATIVE`, `DOCUMENTARY`, `ANIMATION`, or `GENRE_HORROR`, a whole-minute `runtime_minutes`, a `rating` of `G`, `PG`, `PG13`, `R`, or `NC17`, a `release_pattern` of `WIDE`, `LIMITED`, or `PLATFORM`, a `target_release_date` marking the first public playdate at UTC midnight, and a `min_screens_for_wide` threshold. The release pattern is chosen at creation and is immutable; `min_screens_for_wide` is meaningful only for `WIDE` pictures and is ignored for `LIMITED` and `PLATFORM`. The film's `theatrical_window_end` is computed as exactly 90 days after `target_release_date` and defines the exclusive theatrical window. New films carry `lifecycle_status` `PRE_RELEASE` and a `screens_committed` count of 0; `screens_committed` is a computed count of the film's agreements whose `deal_status` is `ACCEPTED`, `IN_PLAY`, or `HELD_OVER` — only live agreements count, and `COMPLETED`, `CANCELLED`, or `DECLINED` agreements do not.

Opening the release moves the film from `PRE_RELEASE` to `IN_RELEASE`. For `LIMITED` and `PLATFORM` pictures there is no screen-count gate. For a `WIDE` picture, the gate is met when `screens_committed` is at least `min_screens_for_wide` — equality meets the gate — and an attempt below the threshold is rejected with `ERR_WIDE_GATE_NOT_MET`. Opening also requires the distributor's posture to be `ACTIVE`, failing with `ERR_DISTRIBUTOR_FROZEN` otherwise, and the request must carry `expected_film_version` per §2.7. A successful open increments the film's `version`.

From `IN_RELEASE`, the film moves automatically to `HOLDOVER_PHASE` the moment any of its agreements first becomes holdover-eligible. A `Booker` may pull a film from `PRE_RELEASE`, `IN_RELEASE`, or `HOLDOVER_PHASE` to the terminal `PULLED` state, but only when no agreement stands in `ACCEPTED`, `IN_PLAY`, or `HELD_OVER` — in-play and held-over bookings must run their course, and accepted ones must be cancelled first. Pulling from `PRE_RELEASE` also cancels every `PROPOSED` or `COUNTERED` agreement and every `SCHEDULED` ancillary window; pulling from `IN_RELEASE` or `HOLDOVER_PHASE` cancels every `SCHEDULED` ancillary window.

### 3.3. Negotiating the Booking Agreement

The heart of the system is the BookingAgreement, which carries two independent state axes. The **deal axis** runs `PROPOSED` → `COUNTERED` → `ACCEPTED` → `IN_PLAY` → `HELD_OVER`, with terminal outcomes `DECLINED`, `CANCELLED`, and `COMPLETED`; negotiation is cyclic, so `PROPOSED` and `COUNTERED` toggle back and forth. The **print axis** runs in parallel from `NOT_ORDERED` through `DCP_QUEUED`, `DCP_SHIPPED`, `DCP_DELIVERED`, `KDM_ISSUED`, `KEY_LIVE`, `PRINT_STRUCK`, and `PRINT_RETURNED` (§3.5). A booking proposal names the picture via `film_id`, the counterparty via `theatre_id`, and the auditorium via `screen_id`, together with the commercial skeleton: an `opening_date` first playdate at UTC midnight, a `min_weeks_committed` count of guaranteed weekly renewals, and four fiscal terms — `week_one_rental_pct`, `rental_decay_per_week`, `floor_pct`, and `per_capita_floor_cents` — plus an optional `aggregate_deal_id` tying the agreement into a circuit-level deal (§3.4). A fresh agreement starts with `deal_status` `PROPOSED`, `print_status` `NOT_ORDERED`, and `weeks_played` at 0.

Creation is guarded by the precedence ladder of §2.11: the distributor must not be `FROZEN`; the film's lifecycle must be `PRE_RELEASE`, `IN_RELEASE`, or `HOLDOVER_PHASE`, failing with `ERR_FILM_NOT_BOOKABLE` otherwise; no conflicting upheld zone clearance may cover the theatre (`ERR_ZONE_CLEARANCE_CONFLICT`, §3.9); every supplied reference must resolve (`ERR_REFERENTIAL_INTEGRITY`); the named screen must belong to the named theatre (`ERR_SCREEN_THEATRE_MISMATCH`); and the screen must be free — not committed to another agreement over overlapping dates and not in `MAINTENANCE` (`ERR_SCREEN_UNAVAILABLE`). The fiscal terms are then validated: `week_one_rental_pct` must lie between 0.00 and 0.95 inclusive, and `floor_pct` must not exceed `week_one_rental_pct`; a violation is rejected with `ERR_INVALID_RENTAL_TERMS` (HTTP 422).

Once proposed, the deal axis cycles. An `Exhibitor` counters a `PROPOSED` agreement, moving it to `COUNTERED` with the proposed counter-terms recorded on the agreement; a `Booker` counters a `COUNTERED` agreement, returning it to `PROPOSED`. Every counter-offer carries `expected_booking_agreement_version`, is rejected with `ERR_STALE_VERSION` when stale, re-validates the fiscal terms against `ERR_INVALID_RENTAL_TERMS`, and increments the agreement's `version`. Declining is the one-way door: the `Exhibitor` declines from `PROPOSED`, the `Booker` declines from `COUNTERED`, and the agreement lands in terminal `DECLINED`.

Acceptance is symmetric and role-mirrored: the `Exhibitor` accepts a `PROPOSED` agreement, and the `Booker` accepts a `COUNTERED` one. Acceptance re-checks the full guard set — distributor posture, film bookability, the theatre being `ACTIVE` (`ERR_THEATRE_INACTIVE`), the screen still `AVAILABLE`, the zone-clearance check, and the stale-version check. On success the deal moves to `ACCEPTED`, the screen flips to `BOOKED`, the film's `screens_committed` increments by one, the agreement's `version` advances by exactly one — acceptance is applied as a single mutation of the agreement, even though both `deal_status` and `print_status` change — and the print axis fires: a shipment record is auto-created in `QUEUED` with its `content_format` taken from the screen's `projection_format`, and `print_status` advances from `NOT_ORDERED` to `DCP_QUEUED`.

A `Booker` may cancel an agreement from `PROPOSED`, `COUNTERED`, or `ACCEPTED`; agreements in `IN_PLAY`, `HELD_OVER`, or `COMPLETED` cannot be cancelled and such attempts fail with `ERR_INVALID_STATE`. Cancelling a previously accepted agreement unwinds every acceptance side effect: the screen returns to `AVAILABLE`, `screens_committed` decrements by one, any shipment not yet `DELIVERED` moves to `RETURNED`, any key in `ISSUED` or `LIVE` is `REVOKED`, and a `print_status` of `KEY_LIVE` rolls back to `DCP_DELIVERED`.

The rental rate applied to each week's settlement is the agreement's `current_week_rental_pct`: start from `week_one_rental_pct`, subtract `rental_decay_per_week` once for each week already played, and take the greater of that difference and `floor_pct`, expressed at 4 decimal places with round-half-up. The decay is a percentage-point decrement — a value of 0.05 removes five percentage points per elapsed week. The figure is recomputed whenever a settlement is settled or written off, whenever the agreement enters `HELD_OVER`, and on any change to `weeks_played`; the aggregate-deal override of §3.4 replaces this computation entirely when it applies. The agreement's `holdover_eligible` flag is computed: it is true exactly when `weeks_played` has reached `min_weeks_committed` and the deal stands in `IN_PLAY`.

### 3.4. Aggregate Circuit Deals

For circuit-level negotiations, a `Booker` drafts an AggregateDeal naming the `film_id` and the `circuit` it applies to — matched against each theatre's `circuit` — with a single `aggregate_rental_pct`, a `min_screens` participation threshold, and a single `aggregate_house_allowance_cents` covering the entire circuit per week. The deal's `deal_status` begins at `DRAFT`; the full enumeration is `DRAFT`, `ACTIVE`, `CLOSED`, and `VOIDED`. Activation moves a draft to `ACTIVE` and requires at least `min_screens` participating agreements standing in `ACCEPTED` or `IN_PLAY`.

An `ACTIVE` aggregate deal overrides per-agreement economics for any agreement whose `aggregate_deal_id` references it. The effective rental percentage is simply `aggregate_rental_pct` — flat, with no weekly decay and no floor; `weeks_played`, `floor_pct`, and `rental_decay_per_week` are all ignored. House allowance changes shape too: instead of each theatre's own weekly allowance, the circuit-wide `aggregate_house_allowance_cents` is divided equally across the participating accepted agreements, and when the division is not exact the remainder cents go to the screen whose agreement has the earliest `created_at`. The aggregate split applies only to final settlements; provisional estimates continue to use the plain per-theatre allowance (§3.7).

### 3.5. Prints and Keys: DCP Logistics and KDM Windows

Content logistics live on the booking's print axis, which advances independently of the deal axis. When acceptance queues a print, the `Booker` dispatches the shipment by supplying a `content_format` — `DCP_2K`, `DCP_4K`, or `FILM_35MM` — and a courier `tracking_number`; this requires the print axis to stand at `DCP_QUEUED`. The dispatch creates the shipment record already `IN_TRANSIT` with `shipped_at` stamped by the server, and advances `print_status` to `DCP_SHIPPED`. When the exhibitor receives the content, an `Exhibitor` marks the shipment delivered; this requires the shipment to be `IN_TRANSIT` and the deal to stand in `ACCEPTED` or `IN_PLAY`. Delivery stamps `delivered_at`, moves the shipment to `DELIVERED`, and advances the print axis to `DCP_DELIVERED`.

With content in house, the `Booker` issues a KDM by supplying `valid_from_utc`, `valid_until_utc`, and the target screen's `screen_cert_fingerprint`. Issuance requires the print axis at `DCP_DELIVERED` — otherwise `ERR_PRINT_NOT_READY` — and the proposed window must not overlap another issued or live key on the same screen under the half-open semantics of §2.9, failing with `ERR_KDM_WINDOW_CONFLICT`. A key carries no `screen_id`; "the same screen" is identified by `screen_cert_fingerprint`, so the conflict check spans every `ISSUED` or `LIVE` key carrying the same fingerprint on any booking agreement of the same distributor, not only keys of the booking at hand. A successful issuance creates the key in `ISSUED` and moves the print axis to `KDM_ISSUED`. From there the clock takes over: when `logical_clock_utc` reaches `valid_from_utc`, the key goes `LIVE` and the print axis advances to `KEY_LIVE`; when the clock reaches `valid_until_utc` the key becomes `EXPIRED` — the end boundary is exclusive, so at exactly that instant the key is no longer valid. Key expiry does not auto-complete an agreement in `IN_PLAY`; it blocks the booking from further playdates until the window is extended.

Play begins automatically: an agreement in `ACCEPTED` moves to `IN_PLAY` as soon as the logical clock has reached its `opening_date` and its print axis stands at `KEY_LIVE`.

Windows can be managed. Extending a key from `ISSUED` requires the new `valid_until_utc` to be strictly later than the current one; extending from `LIVE` requires only that the key still be live. Either extension moves the original record to `EXTENDED` and creates a superseding key in `ISSUED` carrying the new window. Extension is guarded by the same window-conflict rule as issuance: a proposed new window that overlaps another issued or live key on the same screen is rejected with `ERR_KDM_WINDOW_CONFLICT`. Revoking a key — whether from `ISSUED` or `LIVE` — moves it to `REVOKED`, and if the print axis stood at `KEY_LIVE` it rolls back to `DCP_DELIVERED`; cancelling a booking agreement revokes its issued and live keys as part of the unwind in §3.3.

Two failure exits complete the picture. A `Booker` may mark a queued or in-transit shipment lost, moving it to `LOST`; when the deal stands in `ACCEPTED` the print axis resets to `DCP_QUEUED` so a replacement can be dispatched. After the agreement completes, the print axis moves to `PRINT_STRUCK` automatically and the live key expires if it has not already expired or been revoked; the `Booker` then marks the shipment returned from `PRINT_STRUCK`, moving the shipment to `RETURNED` and the print axis to `PRINT_RETURNED`. A shipment cancelled before delivery moves straight to `RETURNED` per the cancellation unwind.

### 3.6. Reporting the Box Office and Closing the Week

Each playdate's takings enter the system as a BoxOfficeReport. An `Exhibitor` files a report with a `report_date` at UTC midnight, the day's `gross_cents`, and the day's `admissions` ticket count; the report is created in `DRAFT`. The report date must fall within the distributor's current or prior `week_epoch`, and the same window is re-checked when the report is submitted — a date outside the window is rejected with `ERR_REPORT_OUTSIDE_WINDOW` (HTTP 422) at either step. For this window, calendar dates map to week indexes as seven-day weeks anchored at the logical clock's startup default `2026-05-01T00:00:00Z` (§2.5): a report date's week index is `floor((report_date − 2026-05-01T00:00:00Z) / 7 days)`, so week index 0 is the seven days beginning at the anchor. The window admits exactly week indexes `week_epoch − 1` and `week_epoch`; a date before the anchor yields a negative index and is always outside the window. Submitting moves a draft to `SUBMITTED` and requires the agreement's deal axis to be `IN_PLAY` or `HELD_OVER`.

Corrections have two lanes. An `Exhibitor` may void a report still in `DRAFT`. A `Booker` may void a `SUBMITTED` report, but only while that week's settlement is still `PROVISIONAL`; voiding a submitted report recomputes the provisional settlement's gross with the voided report excluded. Voided reports land in terminal `VOIDED`.

The weekly close, run by a `SettlementClerk`, is the system's checkpoint. Closing the week increments the distributor's `week_epoch` by one, locks every `SUBMITTED` report belonging to the prior week — stamping each with a `week_index` equal to the epoch — and walks each affected settlement through `PROVISIONAL` → `PENDING_FINAL` → `FINALIZED` in that order. During the same close the system computes a holdover recommendation for every in-play eligible agreement (§3.8), completes every agreement whose commitment has run its course (§3.8), expires every zone clearance whose closed window has passed, expires every key whose end instant has been reached, and flags any scheduled ancillary window whose start violates the theatrical window (§3.9).

### 3.7. Settlement: Provisional Estimates, Finalization, and Disputes

A Settlement exists for each booking-week and carries a `week_index` identifying the epoch it covers. Two variants coexist, recorded in the settlement's `variant` field. A `PROVISIONAL` variant is the forward-looking in-week preview: its gross sums reports in `DRAFT`, `SUBMITTED`, and `LOCKED` alike, and its house allowance is the plain per-theatre `house_allowance_cents` with no aggregate allocation. The `FINAL` variant is the locked form: its gross sums `LOCKED` reports only, and an active aggregate deal's allowance is split per screen as described in §3.4. The settlement's lifecycle `status` — which also begins at `PROVISIONAL` and runs through `PENDING_FINAL`, `FINALIZED`, and on to terminal `SETTLED` or `WRITTEN_OFF`, with `DISPUTED` as the exception state — is a separate axis from `variant`.

When a settlement finalizes, its economics are computed in a pinned ten-step order. First, `gross_cents` is the sum of the week's `LOCKED` reports for the booking. Second, `house_allowance_cents` is either the theatre's weekly allowance or the aggregate split with its remainder rule. Third, `net_cents` is the gross minus the allowance, floored at zero. Fourth, `rental_pct_applied` is the agreement's `current_week_rental_pct`, which may already reflect an aggregate override. Fifth, the pre-floor distributor share is `net_cents` multiplied by `rental_pct_applied`, rounded half-up to whole cents — the only rounding step in the pipeline. Sixth, the per-capita floor is the week's total `admissions` multiplied by `per_capita_floor_cents`. Seventh, `distributor_share_cents` is the greater of the pre-floor share and the per-capita floor. Eighth, `exhibitor_share_cents` is the net minus the distributor share; should the per-capita floor push the distributor share above the net, the exhibitor share is zero and the shortfall is recorded as a negative exhibitor share — a deliberate fiscal edge, preserved rather than clamped. Ninth, `marketing_offset_cents` is the smaller of the linked commitment's `outstanding_cents` and the product of its `committed_cents` with its `coop_share_pct`. Tenth, `final_distributor_payout_cents` is the distributor share plus the marketing offset.

The marketing offset is drawn down as a waterfall. Every MarketingCommitment matching the settlement's film-and-theatre pair is visited in `created_at` ascending order; from each, the draw is the smaller of the remaining offset and that commitment's `outstanding_cents`, added to its `spent_cents`, until the offset is fully allocated. Each draw is computed in integer cents per line before any summation — this per-line-then-sum order is pinned, because summing first and rounding once would drift the total by a cent per settlement. A commitment's `outstanding_cents` is always its `committed_cents` minus its `spent_cents`.

The lifecycle itself is system-driven at the front and role-driven at the back. The first `LOCKED` report for the week moves a settlement from `PROVISIONAL` to `PENDING_FINAL`, recomputing the final-variant fields from locked reports: the settlement's `variant` flips to `FINAL` at this transition, and the recomputation covers the full final economics of the ten-step order above — locked-only gross, the aggregate-split house allowance where §3.4 applies, and the marketing offset figure — while the waterfall's draw-down against each commitment's `spent_cents` still fires only when the settlement reaches `FINALIZED`. At the weekly close, once no `DRAFT` or `SUBMITTED` reports remain for the week, the settlement moves to `FINALIZED`; finalization applies the marketing offset, adds it to the commitment's `spent_cents`, and deliberately leaves the market's `coop_committed_cents` untouched — only spend moves at this point.

From `FINALIZED`, a `SettlementClerk` marks the settlement `SETTLED` once the exhibitor has paid; a `SettlementClerk` may instead write off a settlement older than two week-epochs, moving it to `WRITTEN_OFF`. Both actions advance the agreement's `weeks_played` by one and trigger recomputation of `current_week_rental_pct` for the coming week. Segregation of duties binds both settlement and dispute resolution: the clerk's `X-User-ID` must not be the identifier that created the underlying booking agreement, or the request fails with `ERR_SOD_VIOLATION` (HTTP 403).

An `Exhibitor` who disputes a finalized settlement moves it to `DISPUTED`, and the cascade is immediate: the distributor's `lifecycle_posture` flips to `FROZEN`, blocking new booking creation, counter-offers, and acceptances with `ERR_DISTRIBUTOR_FROZEN` while any dispute stands open. A `SettlementClerk` — again not the agreement's creator — resolves the dispute, returning the settlement to `FINALIZED`, recomputing `final_distributor_payout_cents` with the resolution delta, and restoring the distributor to `ACTIVE` when no other `DISPUTED` settlement remains anywhere in its tree.

### 3.8. Holdover Decisions and Screen Reallocation

Once an agreement has played its committed weeks, the distributor decides whether to hold it over. A `Booker` may hold over an agreement standing in `IN_PLAY` whose `holdover_eligible` is true; attempting a holdover before `weeks_played` has reached `min_weeks_committed` is rejected with `ERR_HOLDOVER_NOT_ELIGIBLE`. The manual holdover carries a Booker-supplied `rationale`, moves the deal to `HELD_OVER`, and records a HoldoverDecision whose `decision` is `HOLD`; the decision's `week_index` is the epoch in which the decision was made, and its `prior_week_gross_cents` is the sum of the prior week's locked reports. Entering holdover does not itself advance `weeks_played` — that increment arrives through the next weekly settlement cycle. Releasing from holdover returns the deal to `IN_PLAY` and records a decision of `RELEASE`.

The weekly close also renders an automatic recommendation for every in-play, holdover-eligible agreement. When the prior week's locked gross is at least the product of `min_weeks_committed` and 100000 cents — one thousand dollars per committed week — the system records a decision of `AUTO_HOLD`; below that threshold it records `AUTO_RELEASE`. The boundary is inclusive: a gross exactly equal to the threshold recommends the hold.

Completion is the close's other job. An in-play agreement completes during the close when `weeks_played` has reached `min_weeks_committed`, no further holdover has been requested, and its latest settlement stands in `SETTLED` or `WRITTEN_OFF`. A held-over agreement completes during the close once its holdover was released in the prior week and its latest settlement is `SETTLED`. Completion moves the deal to `COMPLETED`, frees the screen back to `AVAILABLE`, and decrements the film's `screens_committed` by one. For a `WIDE` picture whose committed count has now fallen below `min_screens_for_wide`, every other `ACCEPTED` agreement for the film is re-evaluated: none is auto-cancelled, but any future acceptance re-checks the wide gate. Completion also strikes the print, per §3.5.

### 3.9. Marketing Co-op, Zone Clearance, and the Ancillary Handoff

**Co-op commitments.** A `MarketingLead` creates a MarketingCommitment inside a market, naming the `film_id` it promotes, an optional `theatre_id` for the exhibitor co-op partner — null when the commitment is pure-distributor — a `committed_cents` amount, and a `coop_share_pct` expressing the exhibitor's share of spend, so that 0.50 means a fifty-fifty split. The commitment starts in `DRAFT` with `spent_cents` at 0. Committing it requires the film's lifecycle to be `PRE_RELEASE`, `IN_RELEASE`, or `HOLDOVER_PHASE`, and enforces the market's running cap: the market's `coop_committed_cents` plus the new `committed_cents` must not exceed four times its `weekly_coop_budget_cents`. Equality with the cap is permitted; only strict overflow is rejected with `ERR_COOP_BUDGET_EXCEEDED`. A successful commit moves the commitment to `COMMITTED` and adds its `committed_cents` to the market's `coop_committed_cents`. The first finalized settlement referencing the commitment moves it to `ACCRUING` and begins accumulating spend; when a finalization drives its `outstanding_cents` to zero the commitment moves to `SETTLED` and its `committed_cents` come back out of `coop_committed_cents`. A `MarketingLead` may cancel a commitment from `DRAFT` or `COMMITTED` provided nothing has been spent — `spent_cents` must be zero — and cancelling a `COMMITTED` commitment decrements `coop_committed_cents` accordingly.

**Zone clearances.** A `Booker` grants a zone clearance inside a market by naming the `film_id`, the `theatre_id` receiving exclusivity, a `clearance_radius_km`, and a window from `effective_from_utc` to `effective_until_utc`; an optional `parent_dispute_id` marks the grant as a superseding ruling on a prior dispute. The clearance is created `GRANTED`. Conflict detection follows the closed-interval rule of §2.9: two clearances for the same film conflict when the theatres lie within the clearance radius and their windows overlap, both endpoints inclusive — adjacency counts as overlap. The check runs when a clearance is granted and again when a booking is created or accepted; a booking that would land inside another theatre's `UPHELD` clearance radius during an overlapping window is rejected with `ERR_ZONE_CLEARANCE_CONFLICT`. An `Exhibitor` may challenge a grant, moving it to `CHALLENGED`, provided the challenger is a different theatre in the same market — the acting `X-User-ID` must differ from the granted theatre's — and while the dispute is open the challenging theatre cannot create bookings. The `Booker` then rules, passing a `ruling`: upholding keeps the grant, moves the clearance to `UPHELD`, and bars the challenging theatre from booking the film within `clearance_radius_km` for the closed window; overruling reverses the grant, moves the original to `OVERRULED`, creates a superseding clearance whose `parent_dispute_id` points at the original, and cancels every `PROPOSED` or `COUNTERED` agreement belonging to the originally granted theatre. Clearances in `GRANTED` or `UPHELD` expire automatically — moving to `EXPIRED` — once the logical clock has passed `effective_until_utc`; because the window is closed, the clearance is still in force at exactly that instant. The full dispute chain is navigable: a clearance can be read directly by its identifier, and its superseding children can be listed.

**The ancillary handoff.** The exclusive theatrical window ends at `theatrical_window_end`, 90 days after the first playdate. A `Booker` schedules an ancillary window with a `window_kind` of `HOME_VIDEO`, `TVOD`, `SVOD`, or `AIRLINE` and a `scheduled_start_utc`; the scheduled start must be on or after `theatrical_window_end`, failing with `ERR_ANCILLARY_TOO_EARLY` (HTTP 422) otherwise. The request to hand off moves the film to `ANCILLARY_PENDING`: from `IN_RELEASE` it requires every agreement to be terminal — `COMPLETED`, `CANCELLED`, or `DECLINED`, with none in play or held over — and the logical clock to have reached the point seven days before the window end, so scheduling may begin up to a week early while the actual handoff stays gated; from `HOLDOVER_PHASE` it requires the same all-terminal condition. The handoff itself is automatic: once the logical clock reaches `theatrical_window_end` and the film stands in `ANCILLARY_PENDING` with at least one `SCHEDULED` window, every scheduled window moves to `HANDED_OFF` with `actual_start_utc` stamped, and when the last scheduled window hands off the film moves to `ANCILLARY_RELEASED`. A `Booker` may cancel a scheduled window while the logical clock is still before its `scheduled_start_utc`, moving it to `CANCELLED`. Finally, the weekly close sweeps for violations: a `SCHEDULED` window whose start precedes the theatrical window end — possible only where an early-start override applies — is recorded as `VIOLATED` for audit when no such override is in effect, leaving the film's lifecycle unchanged.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; reads, state transitions, and other modifications of an existing resource return `200 OK`. Request payloads, preconditions, and side effects for each operation are specified by the narratives in §2 and §3; the table below is the routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/distributors` | Create a Distributor | PlatformAdmin |
| GET | `/distributors/{did}` | Read a Distributor (posture, week epoch, logical clock) | All roles |
| GET | `/distributors` | List Distributors | All roles |
| POST | `/distributors/{did}/close_box_office_week` | Close the box-office week; run the weekly cascade | SettlementClerk |
| POST | `/_clock/set_current_utc` | Advance the global logical clock | PlatformAdmin |
| POST | `/distributors/{did}/films` | Create a Film | Booker |
| GET | `/distributors/{did}/films/{fid}` | Read a Film | All roles |
| GET | `/distributors/{did}/films` | List Films for a distributor | All roles |
| POST | `/distributors/{did}/films/{fid}/open_release` | Open the film for public playdates; WIDE applies the screen gate | Booker |
| POST | `/distributors/{did}/films/{fid}/pull` | Pull the film from release | Booker |
| POST | `/distributors/{did}/films/{fid}/request_ancillary_handoff` | Request handoff to ancillary distribution | Booker |
| POST | `/distributors/{did}/markets` | Create a Market | PlatformAdmin |
| GET | `/distributors/{did}/markets/{mid}` | Read a Market | All roles |
| GET | `/distributors/{did}/markets` | List Markets | All roles |
| POST | `/distributors/{did}/theatres` | Create a Theatre | PlatformAdmin |
| GET | `/distributors/{did}/theatres/{tid}` | Read a Theatre | All roles |
| GET | `/distributors/{did}/theatres` | List Theatres | All roles |
| POST | `/distributors/{did}/theatres/{tid}/suspend` | Suspend a theatre (blocks new bookings) | PlatformAdmin |
| POST | `/distributors/{did}/theatres/{tid}/screens` | Create a Screen | PlatformAdmin |
| GET | `/distributors/{did}/theatres/{tid}/screens/{sid}` | Read a Screen | All roles |
| GET | `/distributors/{did}/theatres/{id}/screens` | List Screens for a theatre | All roles |
| POST | `/distributors/{did}/aggregate-deals` | Create an AggregateDeal (circuit-level rental override) | Booker |
| GET | `/distributors/{did}/aggregate-deals/{aid}` | Read an AggregateDeal | PlatformAdmin, Booker, SettlementClerk, Auditor |
| GET | `/distributors/{did}/aggregate-deals` | List AggregateDeals | PlatformAdmin, Booker, SettlementClerk, Auditor |
| POST | `/distributors/{did}/aggregate-deals/{aid}/activate` | Activate an aggregate deal (requires min screens participating) | Booker |
| POST | `/distributors/{did}/booking-agreements` | Propose a new BookingAgreement | Booker |
| GET | `/distributors/{did}/booking-agreements/{baid}` | Read a BookingAgreement | All roles |
| GET | `/distributors/{did}/booking-agreements` | List BookingAgreements | All roles |
| POST | `/distributors/{did}/booking-agreements/{baid}/counter` | Counter-offer (cyclic negotiation round) | Booker, Exhibitor |
| POST | `/distributors/{did}/booking-agreements/{baid}/accept` | Accept the current terms; locks the deal and queues the print | Booker, Exhibitor |
| POST | `/distributors/{did}/booking-agreements/{baid}/decline` | Decline the offer | Booker, Exhibitor |
| POST | `/distributors/{did}/booking-agreements/{baid}/cancel` | Cancel the agreement (from PROPOSED, COUNTERED, or ACCEPTED) | Booker |
| POST | `/distributors/{did}/booking-agreements/{baid}/holdover` | Hold the booking over another week | Booker |
| POST | `/distributors/{did}/booking-agreements/{baid}/holdover_release` | Release from holdover; completes at next close | Booker |
| POST | `/distributors/{did}/booking-agreements/{baid}/dcp-shipments` | Create and dispatch a DCP shipment | Booker |
| GET | `/distributors/{did}/booking-agreements/{baid}/dcp-shipments/{sid}` | Read a DCPShipment | PlatformAdmin, Booker, Exhibitor, Auditor |
| GET | `/distributors/{did}/booking-agreements/{id}/dcp-shipments` | List shipments for an agreement | PlatformAdmin, Booker, Exhibitor, Auditor |
| POST | `/distributors/{did}/booking-agreements/{baid}/dcp-shipments/{sid}/mark_delivered` | Mark a shipment delivered | Exhibitor |
| POST | `/distributors/{did}/booking-agreements/{baid}/dcp-shipments/{sid}/mark_returned` | Mark a shipment returned | Booker |
| POST | `/distributors/{did}/booking-agreements/{baid}/dcp-shipments/{sid}/mark_lost` | Mark a shipment lost; resets the print for re-shipment | Booker |
| POST | `/distributors/{did}/booking-agreements/{baid}/kdm-keys` | Issue a KDM | Booker |
| GET | `/distributors/{did}/booking-agreements/{baid}/kdm-keys/{kid}` | Read a KDMKey | PlatformAdmin, Booker, Exhibitor, Auditor |
| GET | `/distributors/{did}/booking-agreements/{id}/kdm-keys` | List KDMKeys for an agreement | PlatformAdmin, Booker, Exhibitor, Auditor |
| POST | `/distributors/{did}/booking-agreements/{baid}/kdm-keys/{kid}/extend` | Extend a KDM validity window | Booker |
| POST | `/distributors/{did}/booking-agreements/{baid}/kdm-keys/{kid}/revoke` | Revoke a KDM | Booker |
| POST | `/distributors/{did}/booking-agreements/{baid}/box-office-reports` | File a daily box office report | Exhibitor |
| GET | `/distributors/{did}/booking-agreements/{baid}/box-office-reports/{rid}` | Read a BoxOfficeReport | PlatformAdmin, Booker, Exhibitor, SettlementClerk, Auditor |
| GET | `/distributors/{did}/booking-agreements/{id}/box-office-reports` | List reports for an agreement | PlatformAdmin, Booker, Exhibitor, SettlementClerk, Auditor |
| POST | `/distributors/{did}/booking-agreements/{baid}/box-office-reports/{rid}/submit` | Submit a DRAFT report | Exhibitor |
| POST | `/distributors/{did}/booking-agreements/{baid}/box-office-reports/{rid}/void` | Void a DRAFT or SUBMITTED report | Exhibitor, Booker |
| GET | `/distributors/{did}/booking-agreements/{baid}/settlements/{sid}` | Read a Settlement | PlatformAdmin, Booker, Exhibitor, SettlementClerk, Auditor |
| GET | `/distributors/{did}/booking-agreements/{id}/settlements` | List settlements for an agreement | PlatformAdmin, Booker, Exhibitor, SettlementClerk, Auditor |
| POST | `/distributors/{did}/booking-agreements/{baid}/settlements/{sid}/mark_settled` | Mark a settlement settled (exhibitor paid) | SettlementClerk |
| POST | `/distributors/{did}/booking-agreements/{baid}/settlements/{sid}/dispute` | Dispute a settlement | Exhibitor |
| POST | `/distributors/{did}/booking-agreements/{baid}/settlements/{sid}/resolve_dispute` | Resolve a disputed settlement | SettlementClerk |
| POST | `/distributors/{did}/booking-agreements/{baid}/settlements/{sid}/write_off` | Write off a settlement (bad debt) | SettlementClerk |
| GET | `/distributors/{did}/booking-agreements/{id}/holdover-decisions` | List holdover decisions for an agreement | PlatformAdmin, Booker, Exhibitor, Auditor |
| POST | `/distributors/{did}/markets/{mid}/marketing-commitments` | Create a marketing co-op commitment | MarketingLead |
| GET | `/distributors/{did}/markets/{mid}/marketing-commitments/{mcid}` | Read a MarketingCommitment | PlatformAdmin, Booker, MarketingLead, Auditor |
| GET | `/distributors/{did}/markets/{id}/marketing-commitments` | List commitments for a market | PlatformAdmin, Booker, MarketingLead, Auditor |
| GET | `/distributors/{did}/marketing-commitments` | List commitments across the distributor | PlatformAdmin, Booker, MarketingLead, Auditor |
| GET | `/distributors/{did}/films/{id}/marketing-commitments` | List commitments for a film | PlatformAdmin, Booker, MarketingLead, Auditor |
| GET | `/distributors/{did}/theatres/{id}/marketing-commitments` | List commitments for a theatre | PlatformAdmin, Booker, MarketingLead, Auditor |
| POST | `/distributors/{did}/markets/{mid}/marketing-commitments/{mcid}/commit` | Commit a draft (validates the budget cap) | MarketingLead |
| POST | `/distributors/{did}/markets/{mid}/marketing-commitments/{mcid}/cancel` | Cancel a draft or unspent commitment | MarketingLead |
| POST | `/distributors/{did}/markets/{mid}/zone-clearances` | Grant a zone clearance | Booker |
| GET | `/distributors/{did}/markets/{mid}/zone-clearances/{zid}` | Read a ZoneClearance within its market | PlatformAdmin, Booker, Exhibitor, Auditor |
| GET | `/distributors/{did}/markets/{id}/zone-clearances` | List clearances for a market | PlatformAdmin, Booker, Exhibitor, Auditor |
| GET | `/distributors/{did}/zone-clearances` | List clearances across the distributor | PlatformAdmin, Booker, Exhibitor, Auditor |
| GET | `/distributors/{did}/films/{id}/zone-clearances` | List clearances for a film | PlatformAdmin, Booker, Exhibitor, Auditor |
| GET | `/distributors/{did}/theatres/{id}/zone-clearances` | List clearances granted to a theatre | PlatformAdmin, Booker, Exhibitor, Auditor |
| GET | `/distributors/{did}/zone-clearances/{id}` | Read a ZoneClearance by id (parent-chain derivation) | PlatformAdmin, Booker, Exhibitor, Auditor |
| GET | `/distributors/{did}/zone-clearances/{id}/children` | List superseding rulings pointing at this clearance | PlatformAdmin, Booker, Exhibitor, Auditor |
| POST | `/distributors/{did}/markets/{mid}/zone-clearances/{zid}/challenge` | Challenge a granted clearance | Exhibitor |
| POST | `/distributors/{did}/markets/{mid}/zone-clearances/{zid}/rule` | Rule on a challenged clearance (uphold or overrule) | Booker |
| POST | `/distributors/{did}/films/{fid}/ancillary-windows` | Schedule an ancillary window | Booker |
| GET | `/distributors/{did}/films/{fid}/ancillary-windows/{awid}` | Read an AncillaryWindow | PlatformAdmin, Booker, Auditor |
| GET | `/distributors/{did}/films/{id}/ancillary-windows` | List ancillary windows for a film | PlatformAdmin, Booker, Auditor |
| POST | `/distributors/{did}/films/{fid}/ancillary-windows/{awid}/cancel` | Cancel a scheduled ancillary window | Booker |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. Trigger conditions are specified where each guard lives, throughout §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_ROLE_FORBIDDEN` | 403 |
| `ERR_SOD_VIOLATION` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENTIAL_INTEGRITY` | 422 |
| `ERR_SCREEN_THEATRE_MISMATCH` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DISTRIBUTOR_FROZEN` | 409 |
| `ERR_FILM_NOT_BOOKABLE` | 409 |
| `ERR_THEATRE_INACTIVE` | 409 |
| `ERR_SCREEN_UNAVAILABLE` | 409 |
| `ERR_ZONE_CLEARANCE_CONFLICT` | 409 |
| `ERR_KDM_WINDOW_CONFLICT` | 409 |
| `ERR_PRINT_NOT_READY` | 409 |
| `ERR_INVALID_RENTAL_TERMS` | 422 |
| `ERR_COOP_BUDGET_EXCEEDED` | 409 |
| `ERR_WIDE_GATE_NOT_MET` | 409 |
| `ERR_ANCILLARY_TOO_EARLY` | 422 |
| `ERR_REPORT_OUTSIDE_WINDOW` | 422 |
| `ERR_HOLDOVER_NOT_ELIGIBLE` | 409 |
| `ERR_INVALID_REQUEST` | 400 |

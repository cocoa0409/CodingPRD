# Visitor Management & Lobby Check-In API — Product Requirements Document

## 1. Introduction

Modern corporate campuses face a deceptively hard problem: every person who walks through the lobby must be pre-registered, screened against a security watchlist, bound by the right legal agreements, issued a physical badge, counted against floor occupancy, and accounted for the instant a fire alarm sounds — all while the front desk is moving fast and contractors, couriers, and one-off guests stream past a single kiosk. This document specifies the Visitor Management & Lobby Check-In API, the system of record that governs that entire journey from a visitor's pre-registration through host notification, identity scan, agreement e-signature, watchlist adjudication, badge issuance, and final sign-out.

The platform is built around two intertwined concerns. The first is **compliance and auditability**: every visit is screened, every flagged case is adjudicated by security staff who are structurally prevented from clearing their own guests, and every evacuation produces an immutable roster snapshot. The second is **conserved-quantity bookkeeping**: a site owns a finite pool of physical badges and every floor has a finite occupancy, so the system must hold two inventory invariants exactly true at all times, debiting them on sign-in and crediting them back on sign-out. Layered on top are recurring contractor access windows, time-boxed room and parking reservations, and a package/delivery ledger with per-parcel handling fees. The remainder of this document defines the global contract every endpoint honors (Section 2), the business workflows and their scattered rules (Section 3), the endpoint surface (Section 4), and the canonical error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes exactly three roles, spelled precisely as `SecurityOfficer`, `LobbyAttendant`, and `Host`. A request that omits either header, or that presents an `X-User-Role` value outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the acting role is not permitted to invoke the targeted endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The three roles differ in how `X-User-ID` relates to persisted data. When `X-User-Role` is `Host`, the role is **entity-backed**: `X-User-ID` equals the `id` of the acting `Host` row, and any ownership check on a resource that references a host compares that resource's host foreign key to `X-User-ID`. When `X-User-Role` is `SecurityOfficer` or `LobbyAttendant`, the role is an **opaque operator identifier** not tied to any persisted entity; the server treats it as a free-form staff identifier and does not compare it to any entity's `id`. One consequence of the host being entity-backed matters for adjudication: when a `SecurityOfficer` clears or denies a flagged visit, the officer's `X-User-ID` is checked against that visit's `host_id`, and the two must differ (see Section 3.4).

`SecurityOfficer` owns all site, floor, host, watchlist, meeting-room, parking, and contractor configuration; is the only role that adjudicates flagged visits, manages contractor passes, triggers evacuations, and drives the test clock. `LobbyAttendant` is the front-desk kiosk operator who pre-registers visitors, runs screening, signs visitors in and out, and logs deliveries. `Host` is the employee being visited, who may pre-register their own guests, attach and e-sign agreements, pick up their own deliveries, and read their own billing. Read access to collections and individual resources is broadly shared; the per-endpoint authorization is enumerated in Section 4.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items skipped before the page begins and defaults to 0. Unless a specific workflow states otherwise, list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order, with ties on identical `created_at` broken by ascending `id`. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `has_more` is `true` exactly when `offset` plus the number of items on the returned page is less than `total_count`.

### 2.4. Common Resource Properties

Every persisted resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp expressed in ISO 8601 UTC with three fractional digits, stamped when the resource is first created. All entities in this system — `Site`, `Floor`, `Host`, `WatchlistEntry`, `MeetingRoom`, `ParkingSpace`, `Visit`, `Agreement`, `ContractorPass`, `DeliveryLog`, and `EvacuationEvent` — additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits) and an integer `version`. The `updated_at` field is refreshed on every mutation to the resource, and `version` is a non-negative integer that increments by one on every mutation. A freshly created resource is minted with `version` 0 — creation is the first persist, not a mutation of pre-existing state — and its `updated_at` is set equal to its `created_at` at that moment; the first subsequent mutation advances `version` to 1. Derived-field recomputations are mutations too: when a sign-in changes a floor's occupancy, that floor's `updated_at` and `version` advance just as they would for a direct edit. Clients never supply `id`, `created_at`, `updated_at`, or `version`; the server owns them.

### 2.5. Hierarchical Consistency and Cascading Side Effects

Many operations in this system touch more than one resource. When that happens, the system applies every consequence immediately and atomically, and each affected resource records its own mutation. Two examples anchor the pattern. When a visit is denied — whether automatically at screening or by a security officer's adjudication — every agreement attached to that visit that is still in `PENDING` status is cascaded to `VOID`; this is a two-level cascade from the visit down to its agreements. When a visitor signs in, a single request advances the visit, debits the floor's occupancy counters, debits the site's badge counters, increments the host's notification counter, and — on the very first sign-in of a contractor-covered visit — increments the sponsoring contractor pass's covered-visit counter. Each of those touched resources independently bumps its own `updated_at` and `version`. Wherever a side effect is described in Section 3, treat it as mandatory and immediate, not best-effort.

### 2.6. Nested and Referenced Resource Validation

Although the URL topology is flat — every collection is a top-level peer such as `/sites`, `/floors`, `/visits` — requests routinely reference other resources by foreign key in their bodies and by identifier in their paths. The system validates path identifiers left to right and rejects the first one that does not resolve to an existing resource with `ERR_NOT_FOUND` (HTTP 404). The same `ERR_NOT_FOUND` covers any foreign-key value in a request body that points at a non-existent row — for example, a `floor_id` or `host_id` on a visit, or a `visit_id` on an agreement, that names no such resource. Existence is always checked before any state or business rule is evaluated.

### 2.7. Validation Order and Precedence

When several rules could reject one request, they are evaluated in a fixed precedence so the returned error is deterministic. Authentication comes first: missing or unknown headers yield `ERR_UNAUTHENTICATED` (HTTP 401). Authorization comes second: a role not permitted on the endpoint yields `ERR_FORBIDDEN_ROLE` (HTTP 403). Existence comes third: unresolved path identifiers or foreign keys yield `ERR_NOT_FOUND` (HTTP 404). Request well-formedness comes fourth: a missing required body field, an illegal enum value, or a numeric value outside its declared constraint (such as a negative `badge_total`) yields `ERR_INVALID_REQUEST` (HTTP 422). Optimistic-concurrency checks come fifth, on the two version-guarded write endpoints, yielding the stale-version errors described in Section 2.8 (HTTP 412). The state-machine guard comes sixth: a target resource that is not in a legal state for the requested transition yields `ERR_INVALID_STATE` (HTTP 409). Only after all of those pass does the system evaluate the domain-specific business-safety, referential, temporal, and capacity rules. Within the sign-in workflow specifically, the ordering of those domain checks is spelled out in Section 3.6.

### 2.8. Optimistic Concurrency Control on Sign-In and Clearance

Two write endpoints are guarded by optimistic concurrency control, because each makes a decision against a counter or a status that another actor may have moved since the client last read it. In both cases the guard is expressed purely in terms of the client's last-observed `version` of a parent resource, not in terms of requests overlapping in time.

The first is signing a visitor in. The sign-in request must include `expected_floor_version`, carrying the `version` of the target `Floor` that the attendant last observed. If that value does not equal the floor's current `version` — because another sign-in or sign-out has already changed that floor's occupancy and therefore the attendant's view of its `available_slots` is stale — the request is rejected with `ERR_STALE_FLOOR_VERSION` (HTTP 412). This prevents an attendant from making a capacity decision against outdated headroom.

The second is adjudicating a flagged visit. The clearance request must include `expected_visit_version`, carrying the `version` of the target `Visit` that the security officer last observed. If that value does not equal the visit's current `version` — because the screening result was re-evaluated, the `risk_score` rewritten, or the status moved after the officer loaded the case — the request is rejected with `ERR_STALE_VISIT_VERSION` (HTTP 412). Both `expected_floor_version` and `expected_visit_version` are required, non-optional fields on their respective endpoints. No other endpoint in the system accepts or requires a version field.

### 2.9. Badge Inventory and Floor Occupancy Invariants

Two conserved quantities run through the entire system, and both are recomputed as aggregates rather than trusted as free-floating counters. For each `Site`, `badge_in_use` is the count of visits at that site currently in `SIGNED_IN` status, and `badge_available` is `badge_total` minus `badge_in_use`. The badge-inventory invariant holds at all times: `badge_total` always equals `badge_in_use` plus `badge_available`. For each `Floor`, `current_occupancy` is the count of visits with that `floor_id` currently in `SIGNED_IN` status, and `available_slots` is `capacity` minus `current_occupancy`. The floor-occupancy invariant likewise holds at all times: `capacity` always equals `current_occupancy` plus `available_slots`. Signing a visitor in debits both pools by one; signing the visitor out is the compensating action that credits both pools back by one, restoring each invariant exactly. These are integer counts; there is no fractional bookkeeping.

### 2.10. Precision and Rounding

Monetary amounts in this system are carried in integer cents, and the one place rounding occurs — the per-parcel delivery handling surcharge — uses the round-half-up convention to the nearest whole cent, applied per parcel before any summation (see Section 3.8). Durations are carried in whole minutes. The visit duration rounds elapsed time up to the next whole minute (ceiling), and the contractor billing tiers bill each started hour, again rounding the number of started hours up (ceiling). The watchlist `risk_score` is an integer clamped to the inclusive range from 0 to 100. Wherever a computation is described in Section 3, the stated rounding direction is exact and must not be substituted with a different rounding mode.

## 3. Business Logic & Workflows

### 3.1. Configuring the Site: Buildings, Floors, Rooms, Parking, and Hosts

Before any visitor can arrive, a `SecurityOfficer` provisions the physical and organizational topology. A **site** represents a building and is created with a display `name`, an optional IANA `timezone` string such as `America/New_York` (defaulting to `UTC` when omitted), and a `badge_total` giving the size of the site's physical badge pool. The `badge_total` must be zero or greater; a negative value is rejected as a constraint violation. At creation the site's `badge_in_use` is zero and its `badge_available` equals `badge_total`, establishing the badge-inventory invariant from the first moment.

A **floor** belongs to a site through its `site_id` and is created with a `label` such as `L3` and a `capacity` giving the maximum number of visitors who may simultaneously occupy it; `capacity` must be at least 1. A freshly created floor has `current_occupancy` of zero and `available_slots` equal to `capacity`. A **meeting room** belongs to a floor through its `floor_id` and is created with a `name` and a `seats` count that must be at least 1. A **parking space** belongs to a site through its `site_id` and is created with a `bay_label` such as `P12`.

A **host** is the employee a visitor comes to see. A host belongs to a site through its `site_id` and is created with a `full_name`, an `email` used for arrival notifications, and an optional `department` drawn from `ENGINEERING`, `SALES`, `FACILITIES`, or `EXECUTIVE` (defaulting to `FACILITIES`). Each host tracks a `notify_count` that starts at zero and counts how many host-notification side effects have fired for that host across its lifetime.

### 3.2. The Watchlist

A `SecurityOfficer` maintains the security **watchlist**. Each watchlist entry is scoped to a site through its `site_id` and declares a `match_type` of either `NAME` or `COMPANY`, indicating which visitor attribute it screens against, together with a `match_value_normalized` — the lowercased, trimmed value to compare against. A `NAME` entry screens against a visitor's legal name and a `COMPANY` entry screens against a visitor's company. Each entry carries a `severity` of either `REVIEW` or `DENY`, defaulting to `REVIEW`, and an `active` boolean defaulting to `true` that determines whether the entry participates in screening at all. A `REVIEW` entry routes a matching visit to manual security review; a `DENY` entry hard-blocks the visit. Only `SecurityOfficer` may create, read, or list watchlist entries.

### 3.3. Pre-Registering a Visit and Booking Resources

A visit is pre-registered by a `Host` (registering their own guest) or a `LobbyAttendant`. The creating request supplies the `site_id`, the `host_id` of the host being visited, the `floor_id` the visitor will occupy, the visitor's `visitor_full_name` and `visitor_company`, and the planned `scheduled_start` and `scheduled_end` timestamps. It may optionally supply a `room_id` to book a meeting room, a `parking_space_id` to reserve a bay, a `contractor_pass_id` when the visit is covered by a recurring contractor pass (left null for one-off visitors), and an `id_scanned` boolean recording whether a government photo ID was scanned at the kiosk (defaulting to `false`). A newly pre-registered visit begins in `PREREGISTERED` status with a `risk_score` of 0, and its system-managed `sign_in_at`, `sign_out_at`, `visit_duration_minutes`, and `badge_number` remain null until the relevant lifecycle moments. Pre-registering a visit fires an arrival-preparation notification: the visited host's `notify_count` is incremented by one.

When a `room_id` is supplied at pre-registration, the booking interval runs from `scheduled_start` up to but not including `scheduled_end` — a half-open interval. The booking is rejected with `ERR_ROOM_CONFLICT` (HTTP 409) if it overlaps any existing booking on that same room; two intervals that merely touch at an endpoint (one ending exactly when the next begins) are adjacent, not overlapping, and are permitted with zero buffer. For both the room overlap check and the parking gap check below, "existing booking" / "existing reservation" means every other visit that references that same `room_id` (respectively `parking_space_id`), regardless of that visit's status — visits in terminal statuses such as `DENIED` or `SIGNED_OUT` continue to hold their booking interval and still cause a conflict. When a `parking_space_id` is supplied, the reservation is held to a stricter standard: it must keep a gap of at least fifteen minutes from every existing reservation on that bay, treated as a closed interval extended by that cleaning buffer on each side. Two parking reservations that merely touch end-to-end are *not* allowed, because they violate the fifteen-minute cleaning gap; a violation is rejected with `ERR_PARKING_CONFLICT` (HTTP 409).

A pre-registered visit's mutable fields may be amended before screening. The amendment request may change `room_id`, `parking_space_id`, `scheduled_start`, `scheduled_end`, and `id_scanned`. The amendment endpoint itself enforces no visit-status precondition: it applies no state-machine guard and never returns `ERR_INVALID_STATE`, so an amendment is accepted on a visit in any status (the "before screening" framing describes the intended workflow moment, not an enforced state check); any field omitted from the request body is left unchanged, and supplying `room_id` or `parking_space_id` as `null` clears that booking. Whenever the room or schedule changes, the meeting-room overlap check is re-run and may reject with `ERR_ROOM_CONFLICT`; whenever the parking space or schedule changes, the parking cleaning-buffer check is re-run and may reject with `ERR_PARKING_CONFLICT`. Both `ERR_ROOM_CONFLICT` and `ERR_PARKING_CONFLICT` therefore guard two operations apiece: visit pre-registration and visit amendment.

### 3.4. Screening, Risk Scoring, and Adjudication

Once a visit is pre-registered, a `LobbyAttendant` or `SecurityOfficer` runs **screening** on it, which is permitted only while the visit is in `PREREGISTERED` status; otherwise the transition is rejected as an invalid state. Screening does two things in one step: it records an audit risk score and it auto-advances the visit to one of three outcomes.

The risk score is computed over the candidate set of watchlist entries whose `site_id` equals the visit's `site_id` and whose `active` flag is `true`; matching is case-insensitive against the entries' normalized values. A name hit occurs when at least one such active entry has `match_type` of `NAME` and a `match_value_normalized` equal to the lowercased, trimmed `visitor_full_name`; a company hit occurs when at least one such active entry has `match_type` of `COMPANY` and a `match_value_normalized` equal to the lowercased, trimmed `visitor_company`. A no-photo-ID condition holds when the visit's `id_scanned` is `false`. The raw score adds 50 for a name hit, 30 for a company hit, and 15 for a missing photo ID; these three contributions are independent and additive. The resulting `risk_score` is the raw total clamped into the inclusive range 0 to 100 — values below 0 become 0 and values above 100 become 100, though with these weights the natural ceiling is 95. The `risk_score` is persisted for audit but does **not** by itself decide the outcome.

The outcome is decided by a severity-dominance rule evaluated in a pinned, total order over the same matching active entries. First the system forms the matching set: active entries for the visit's `site_id` whose `(match_type, match_value_normalized)` matches the visit (NAME against `visitor_full_name`, COMPANY against `visitor_company`). Then it applies dominance: if any matching entry has `severity` of `DENY`, the decision is DENY; otherwise, if any matching entry has `severity` of `REVIEW`, the decision is REVIEW; otherwise the decision is CLEAR. `DENY` strictly dominates `REVIEW`, so a visit that matches both a `DENY` entry and a `REVIEW` entry is denied, not flagged — severity dominance is evaluated before review routing, which makes the result deterministic regardless of entry order. On a CLEAR decision the screening auto-advances the visit from `SCREENING` to `CLEARED`. On a REVIEW decision it auto-advances `SCREENING` to `FLAGGED`, parking the visit for security adjudication. On a DENY decision it auto-advances `SCREENING` to `DENIED`, a terminal state in which no badge is ever printed, and every `PENDING` agreement on the visit is cascaded to `VOID`.

A `FLAGGED` visit awaits adjudication by a `SecurityOfficer`, who issues a clearance carrying a `decision` of either `CLEAR` or `DENY` together with the required `expected_visit_version`. Adjudication is permitted only while the visit is `FLAGGED`. A `CLEAR` decision moves the visit `FLAGGED → CLEARED`; a `DENY` decision moves it `FLAGGED → DENIED` and, as with an auto-denial, cascades every `PENDING` agreement on the visit to `VOID`. Two guards protect this step. First, segregation of duties: the adjudicating officer's `X-User-ID` must not equal the visit's `host_id`, because a host may not clear a flag on their own guest; a violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409). Second, the optimistic-concurrency guard of Section 2.8: a stale `expected_visit_version` is rejected with `ERR_STALE_VISIT_VERSION` (HTTP 412), and the version check precedes the state and segregation checks per Section 2.7. Every successful clearance increments the visit's `version`.

### 3.5. Agreements and E-Signature

A visit may have one or more **agreements** — NDAs, safety waivers, or data policies — attached to it. An agreement is created by a `Host` or `LobbyAttendant` against a `visit_id`, with a `document_kind` of `NDA`, `SAFETY_WAIVER`, or `DATA_POLICY` and a `document_version` label such as `NDA-v3`. A new agreement starts in `PENDING` status, with `signed_at` and `signer_name` null until it is signed.

Signing an agreement is performed by a `LobbyAttendant` or `Host` and requires the `signer_name` to be present in the request, which is then captured on the agreement. A signature is permitted only while the agreement is `PENDING` and only while its parent visit is in one of `PREREGISTERED`, `SCREENING`, `FLAGGED`, or `CLEARED` — the four pre-entry states. Once the parent visit has reached `DENIED`, `SIGNED_IN`, or `SIGNED_OUT`, the agreement can no longer be signed, and the attempt is rejected with `ERR_VISIT_NOT_SIGNABLE` (HTTP 409). These two guards are evaluated in order: the agreement's own `PENDING` status is the state-machine guard of Section 2.7 and is checked first, so an agreement that is not `PENDING` (for example one already cascaded to `VOID`) is rejected with `ERR_INVALID_STATE` (HTTP 409) regardless of its parent visit's state; only once the agreement is confirmed `PENDING` is the parent-visit signable check applied, yielding `ERR_VISIT_NOT_SIGNABLE`. When a visit has been `DENIED` — voiding its `PENDING` agreements — an attempt to sign one of those now-`VOID` agreements therefore returns `ERR_INVALID_STATE`, not `ERR_VISIT_NOT_SIGNABLE`. A successful signature moves the agreement `PENDING → SIGNED` and stamps `signed_at` with the server clock. Separately, an agreement reaches the terminal `VOID` state only by system cascade, when its parent visit transitions to `DENIED`.

### 3.6. Signing a Visitor In and Out

Signing a `CLEARED` visitor in is a `LobbyAttendant` operation and the most heavily guarded transition in the system, because it is the point at which a badge is printed and two conserved pools are debited. The request carries the required `expected_floor_version`. Sign-in is permitted only while the visit is in `CLEARED` status. Beyond the state and concurrency guards already described, the system evaluates a sequence of business preconditions, each with its own rejection code, all returning HTTP 409: the visit's `id_scanned` must be `true`, or the request is rejected with `ERR_ID_NOT_SCANNED`; every agreement attached to the visit must be `SIGNED` with none left `PENDING`, or the request is rejected with `ERR_AGREEMENT_NOT_SIGNED`; if the visit carries a `contractor_pass_id`, the referenced pass must be in `ACTIVE` status, or the request is rejected with `ERR_PASS_NOT_ACTIVE`; and for a contractor-covered visit the `scheduled_start` must fall on or after `access_valid_from` and on or before `access_valid_until`, the inclusive recurring-access window, or the request is rejected with `ERR_PASS_WINDOW`. The floor must then have at least one free slot — `available_slots` of 1 or more — or the request is rejected with `ERR_FLOOR_AT_CAPACITY`; and the site must have at least one free badge — `badge_available` of 1 or more — or the request is rejected with `ERR_NO_BADGE_AVAILABLE`.

When every guard passes, the visit moves `CLEARED → SIGNED_IN`: the server stamps `sign_in_at` with its clock and assigns a printed `badge_number`. The floor's `current_occupancy` increases by one and its `available_slots` is recomputed as `capacity` minus the new occupancy, advancing the floor's `version` (the same `version` the OCC guard reads). The site's `badge_in_use` increases by one and its `badge_available` is recomputed as `badge_total` minus the new in-use count. The visited host's `notify_count` increases by one for the arrival. Finally, if the visit is contractor-covered and this is the first time it has ever reached `SIGNED_IN`, the sponsoring contractor pass's `covered_visit_count` increases by one — a cross-aggregate cascade that fires once per covered visit, not on any later re-entry.

Signing a `SIGNED_IN` visitor out is also a `LobbyAttendant` operation and is permitted only while the visit is `SIGNED_IN`. The visit moves `SIGNED_IN → SIGNED_OUT`, a terminal state, and the server stamps `sign_out_at`. The system computes `visit_duration_minutes` as the elapsed time from `sign_in_at` to `sign_out_at` rounded up to whole minutes: the elapsed number of seconds divided by 60 and rounded up to the next whole minute, with the boundary case of exactly zero elapsed seconds yielding 0 minutes rather than 1. Sign-out is the compensating action for the inventory pools: the floor's `current_occupancy` decreases by one and `available_slots` is recomputed, and the site's `badge_in_use` decreases by one and `badge_available` is recomputed, returning the badge and the floor slot and restoring both invariants exactly.

### 3.7. Recurring Contractor Passes

For contractors who visit repeatedly, a `SecurityOfficer` issues a **contractor pass** sponsored by a host. The pass is created against a `host_id` and declares the `contractor_name` (which matches `visitor_full_name` on the visits it covers), the `contractor_company`, and the inclusive recurring-access window bounded by `access_valid_from` and `access_valid_until`. A new pass starts in `ACTIVE` status with a `covered_visit_count` of zero, which counts the visits carrying this `contractor_pass_id` that have reached `SIGNED_IN` at least once.

The pass status follows a small cyclic state machine, all transitions reserved to `SecurityOfficer`. An `ACTIVE` pass may be suspended, moving `ACTIVE → SUSPENDED`, after which covered visits can no longer sign in until the pass is reactivated; a `SUSPENDED` pass may be reactivated, moving `SUSPENDED → ACTIVE` and restoring coverage. A pass may be revoked from either live state — `ACTIVE → REVOKED` or `SUSPENDED → REVOKED` — and `REVOKED` is terminal. Each of these transitions is permitted only from its stated source status; attempting one from any other status is rejected as an invalid state. As Section 3.6 notes, a contractor-covered sign-in checks that the pass is `ACTIVE` at the moment of sign-in, so a suspended or revoked pass blocks the visitor's entry.

A `SecurityOfficer` or `Host` may read a contractor pass's accrued **parking billing**, a computed total accumulated across every visit covered by the pass that has reached `SIGNED_OUT`. The covered, signed-out visits are processed in ascending `sign_out_at` order, breaking ties by ascending `created_at` (the only common-field fallback used; the `id` is never used for ordering). Each visit's fee is computed from its `visit_duration_minutes` against a three-tier schedule and the per-visit fees are summed in integer cents. The first 60 minutes are free. For a visit lasting more than 60 minutes but no more than 240 minutes, the fee is the number of started hours beyond the free hour — that is, the minutes above 60 divided by 60 and rounded up — multiplied by 200 cents per started hour. For a visit lasting more than 240 minutes, the fee is the full second tier (the 180-minute span from minute 61 through minute 240 is three started hours, charged at 200 cents each) plus, for the time beyond 240 minutes, the number of started hours beyond that point — the minutes above 240 divided by 60 and rounded up — multiplied by 500 cents per started hour. The billing read returns the `pass_id`, the `billing_total_cents`, and the `covered_signed_out_count` of visits that contributed.

### 3.8. Package and Delivery Logging

A `LobbyAttendant` logs an inbound package as a **delivery** addressed to a recipient `host_id`, recording the `carrier` — one of `FEDEX`, `UPS`, `USPS`, `DHL`, or `COURIER` — and a `parcel_fees_cents` array giving the per-parcel handling fee in cents for each parcel in the batch (each a non-negative integer). A new delivery starts in `RECEIVED` status with `picked_up_at` null. At logging time the system computes the `handling_invoice_cents`, the total handling invoice including a surcharge. The surcharge is applied per parcel and the rounding order is pinned: for each fee in `parcel_fees_cents`, in the array order submitted, multiply the fee by 1.075 (a 7.5 percent surcharge), round that single parcel's surcharged amount half-up to whole cents, and only then add it to the running total. Rounding each parcel before summing produces a different total than summing the raw surcharged amounts and rounding once; only the round-per-parcel-then-sum order is correct.

A delivery is handed off by a `LobbyAttendant` or `Host` marking it picked up, which moves it `RECEIVED → PICKED_UP` — a terminal state — and stamps `picked_up_at` with the server clock. Pickup is permitted only while the delivery is `RECEIVED`.

### 3.9. Evacuation Rosters

When a floor must be cleared, a `SecurityOfficer` triggers an **evacuation event** against a `floor_id` with a `triggered_reason` of `FIRE_DRILL`, `FIRE_ALARM`, `GAS_LEAK`, or `OTHER`. At the moment of triggering, the system snapshots the roster: it captures `roster_visit_ids` as the ordered array of `id` values of every visit currently in `SIGNED_IN` status on that floor, ordered by `sign_in_at` ascending and then by `created_at` ascending as the tie-break. The `roster_head_count` is the length of that snapshot array. The roster is an immutable point-in-time record; subsequent sign-ins or sign-outs do not alter an already-captured event.

### 3.10. Deterministic Time Control

Because sign-in times, sign-out times, signature times, duration calculations, and contractor-window checks all depend on the server clock, the system exposes an administrative clock-setting capability reserved to `SecurityOfficer`. Supplying a `now_utc` instant pins the server's current UTC clock to that value for all subsequent server-stamped timestamps, making the time-dependent workflows deterministic. The capability echoes back the `now_utc` it was set to.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that read a resource or list, or that drive a state transition or other modification on an existing resource, return `200 OK`. All request and response bodies follow the envelope of Section 2.2; the precise inputs and side effects of each operation are described in the Section 3 narratives rather than repeated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/sites` | Create a site (badge inventory pool root) | SecurityOfficer |
| GET | `/sites/{siteId}` | Get a site | SecurityOfficer, LobbyAttendant, Host |
| POST | `/floors` | Create a floor under a site | SecurityOfficer |
| GET | `/floors/{floorId}` | Get a floor (includes live occupancy) | SecurityOfficer, LobbyAttendant, Host |
| GET | `/floors` | List floors, optionally filtered by `site_id` | SecurityOfficer, LobbyAttendant, Host |
| POST | `/hosts` | Create a host | SecurityOfficer |
| GET | `/hosts/{hostId}` | Get a host (includes notify count) | SecurityOfficer, LobbyAttendant, Host |
| GET | `/hosts` | List hosts, optionally filtered by `site_id` | SecurityOfficer, LobbyAttendant, Host |
| POST | `/watchlist-entries` | Create a watchlist entry | SecurityOfficer |
| GET | `/watchlist-entries/{entryId}` | Get a watchlist entry | SecurityOfficer |
| GET | `/watchlist-entries` | List watchlist entries, optionally filtered by `site_id` | SecurityOfficer |
| POST | `/meeting-rooms` | Create a meeting room on a floor | SecurityOfficer |
| GET | `/meeting-rooms/{roomId}` | Get a meeting room | SecurityOfficer, LobbyAttendant, Host |
| GET | `/meeting-rooms` | List meeting rooms, optionally filtered by `floor_id` | SecurityOfficer, LobbyAttendant, Host |
| POST | `/parking-spaces` | Create a parking space | SecurityOfficer |
| GET | `/parking-spaces/{spaceId}` | Get a parking space | SecurityOfficer, LobbyAttendant, Host |
| GET | `/parking-spaces` | List parking spaces, optionally filtered by `site_id` | SecurityOfficer, LobbyAttendant, Host |
| POST | `/contractor-passes` | Create a recurring contractor pass sponsored by a host | SecurityOfficer |
| GET | `/contractor-passes/{passId}` | Get a contractor pass | SecurityOfficer, LobbyAttendant, Host |
| GET | `/contractor-passes` | List contractor passes, optionally filtered by `host_id` | SecurityOfficer, LobbyAttendant, Host |
| POST | `/contractor-passes/{passId}/suspend` | Suspend an ACTIVE contractor pass | SecurityOfficer |
| POST | `/contractor-passes/{passId}/reactivate` | Reactivate a SUSPENDED contractor pass | SecurityOfficer |
| POST | `/contractor-passes/{passId}/revoke` | Revoke a contractor pass (terminal) | SecurityOfficer |
| GET | `/contractor-passes/{passId}/billing` | Computed read: tiered parking billing across covered signed-out visits | SecurityOfficer, Host |
| POST | `/visits` | Pre-register a visit (books optional room/parking, notifies host) | Host, LobbyAttendant |
| GET | `/visits/{visitId}` | Get a visit | SecurityOfficer, LobbyAttendant, Host |
| GET | `/visits` | List visits, filterable by `host_id`, `floor_id`, `contractor_pass_id`, `room_id`, `parking_space_id`, `site_id`, `status` | SecurityOfficer, LobbyAttendant, Host |
| PATCH | `/visits/{visitId}` | Update a pre-registered visit's mutable fields before screening | Host, LobbyAttendant |
| POST | `/visits/{visitId}/screen` | Run watchlist screening; computes risk score and auto-advances | LobbyAttendant, SecurityOfficer |
| POST | `/visits/{visitId}/clearance` | Adjudicate a FLAGGED visit (CLEAR or DENY); OCC-guarded on visit version | SecurityOfficer |
| POST | `/visits/{visitId}/sign-in` | Sign a CLEARED visitor in; OCC-guarded on floor version | LobbyAttendant |
| POST | `/visits/{visitId}/sign-out` | Sign a SIGNED_IN visitor out | LobbyAttendant |
| POST | `/agreements` | Attach an NDA/agreement (PENDING) to a visit | Host, LobbyAttendant |
| GET | `/agreements/{agreementId}` | Get an agreement | SecurityOfficer, LobbyAttendant, Host |
| GET | `/agreements` | List agreements, optionally filtered by `visit_id` | SecurityOfficer, LobbyAttendant, Host |
| POST | `/agreements/{agreementId}/sign` | E-sign a PENDING agreement | LobbyAttendant, Host |
| POST | `/deliveries` | Log a received package/delivery for a host; computes handling invoice | LobbyAttendant |
| GET | `/deliveries/{deliveryId}` | Get a delivery | SecurityOfficer, LobbyAttendant, Host |
| GET | `/deliveries` | List deliveries, optionally filtered by `host_id` | SecurityOfficer, LobbyAttendant, Host |
| POST | `/deliveries/{deliveryId}/pickup` | Mark a RECEIVED delivery PICKED_UP | LobbyAttendant, Host |
| POST | `/evacuation-events` | Trigger an evacuation on a floor; snapshots the SIGNED_IN roster | SecurityOfficer |
| GET | `/evacuation-events/{eventId}` | Get an evacuation event (roster snapshot) | SecurityOfficer, LobbyAttendant |
| GET | `/evacuation-events` | List evacuation events, optionally filtered by `floor_id` | SecurityOfficer, LobbyAttendant |
| POST | `/_clock/set` | Test-driving: set the server's current UTC clock | SecurityOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_FLOOR_VERSION` | 412 |
| `ERR_STALE_VISIT_VERSION` | 412 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_ID_NOT_SCANNED` | 409 |
| `ERR_AGREEMENT_NOT_SIGNED` | 409 |
| `ERR_VISIT_NOT_SIGNABLE` | 409 |
| `ERR_PASS_NOT_ACTIVE` | 409 |
| `ERR_PASS_WINDOW` | 409 |
| `ERR_ROOM_CONFLICT` | 409 |
| `ERR_PARKING_CONFLICT` | 409 |
| `ERR_FLOOR_AT_CAPACITY` | 409 |
| `ERR_NO_BADGE_AVAILABLE` | 409 |

# Team Travel Charter API — Product Requirements Document

## 1. Introduction

Professional team travel is a logistics discipline with no margin for improvisation: a single road trip binds together charter aircraft contracts, hotel room blocks, per-diem entitlements, equipment freight, venue security credentials, and a league-mandated rest policy, all against a fixed season budget. When a storm cell grounds the outbound charter six hours before tipoff, the travel department must rebook legs, re-balance manifests, hold hotel inventory, and keep finance informed — without losing track of what the disruption cost.

This document specifies the Team Travel Charter API, the system of record for a professional team's travel department. The API governs the full lifecycle of a trip — from opening a season budget, through building the travel party and contracting lift, to manifests, rooming, per-diem, equipment, disruption recovery, and final cost reconciliation. It is written for the engineers who will implement the service; every behavioral rule stated here is normative.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not permitted to perform the attempted operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The system recognizes ten roles. `TravelOpsAdmin` is the platform-level administrator who creates teams and drives the logical clock. `TravelManager` is the travel department head and owns trip construction, the party roster, charter negotiation, and contingency handling. `TravelCoordinator` is the operations specialist responsible for flight legs, manifests, hotel blocks, and room assignments. `TravelFinanceLead` owns seasons, budgets, contract execution, per-diem administration, and trip close-out. `EquipmentManager` owns equipment and baggage shipments. `SecurityOfficer` performs the first step of the credential workflow and revocations. `VenueCredentialApprover` performs the second step of the credential workflow — approvals and denials. `VendorRep` is the charter vendor's representative and counter-signs contracts. `TeamMember` is a member of the travel party who may submit credential requests and dispute per-diem ledgers. `Any` denotes shared read access: every read endpoint is available to all roles.

Role identity is resolved as follows. When `X-User-Role` is `TeamMember`, `X-User-ID` is the `id` of the acting `TravelPartyMember`; ownership checks on any resource that references a `TravelPartyMember` compare the resource's foreign-key field to `X-User-ID`, and a `TeamMember`'s general read access is limited to their own resources. When `X-User-Role` is any of `TravelOpsAdmin`, `TravelManager`, `TravelCoordinator`, `TravelFinanceLead`, `EquipmentManager`, `SecurityOfficer`, `VenueCredentialApprover`, `VendorRep`, or `Any`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `submitted_by_user_id`, `reviewed_by_user_id`, or `approved_by_user_id` on a `CredentialRequest`, where the credential workflow writes it) but does not compare it to any entity's `id`.

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

List endpoints accept two query parameters. `limit` caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every resource in this API — Team, Season, Trip, TravelPartyMember, CharterContract, FlightLeg, ManifestEntry, HotelBlock, RoomAssignment, PerDiemLedger, EquipmentShipment, ContingencyEvent, and CredentialRequest — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID rendered in the canonical RFC 4122 hyphenated string form — five hyphen-separated groups of 8, 4, 4, 4, and 12 hexadecimal digits (for example, `f47ac10b-58cc-4372-a567-0e02b2c3d479`) — with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that increments on every mutation of the resource, used for optimistic concurrency control.

Date and datetime values on the wire follow two serialization rules. A date or datetime field whose value is supplied by the client in a request body — `game_tipoff_utc` and `return_arrival_utc` on trip creation, `scheduled_depart_utc` and `scheduled_arrive_utc` on leg creation and on rebooking, `detected_at` on contingency creation, and the `service_date`, `check_in_date`, and `cutoff_date` date fields — is stored verbatim and returned exactly as supplied, with no normalization. Every timestamp the server stamps itself — `created_at`, `updated_at`, the `now_utc` returned by the clock-setting capability of §2.8, the `scheduled_arrive_utc` rewritten when a delay is reported under §3.4, `actual_depart_utc`, `actual_arrive_utc`, `executed_at`, `cancelled_at`, `paid_at`, `confirmed_at`, and the envelope's `api_request_timestamp` — is serialized as an ISO 8601 UTC timestamp with exactly three fractional digits and a `Z` suffix, as in `2026-08-01T00:00:00.000Z`. Wherever §3 speaks of a timestamp being set or shifted to an instant, the instant is what is normative, and server-written representations of that instant use this canonical form.

Any mutation described in §3 — including system-driven transitions such as a trip being nudged into `DISRUPTED` by an opened contingency, or a cascade touching child resources — refreshes `updated_at` and increments `version` on every resource it modifies. A mutation that fans out to a parent (for example, a booking change that recomputes a trip's cost rollup) increments the parent's `version` as its own independent mutation.

### 2.5. Hierarchical Addressing and Left-to-Right Path Validation

Resources are addressed through nested paths: a season lives under a team (`{teamId}`, then `{seasonId}`), and nearly everything else lives under a trip (`{tripId}`) — members (`{memberId}`), charter contracts (`{contractId}`), flight legs (`{legId}`) with their manifest entries (`{entryId}`), hotel blocks (`{blockId}`) with their room assignments (`{roomId}`), per-diem ledgers (`{ledgerId}`) under members, equipment shipments (`{shipmentId}`), contingency events (`{eventId}`), and credential requests (`{credId}`). Flat single-resource accessors also exist under `/travel` for every child collection (registering the collection segments `seasons`, `trips`, `members`, `charter-contracts`, `flight-legs`, `manifest-entries`, `hotel-blocks`, `rooms`, `per-diem`, `equipment`, `contingencies`, and `credentials` addressed by `{id}`).

For any nested request, the server validates path identifiers strictly left to right — team first, then season or trip, then the child — and rejects the request with a 404 the moment an identifier fails to resolve within its parent: `ERR_TEAM_NOT_FOUND` for a bad `teamId`, `ERR_SEASON_NOT_FOUND` for a `seasonId` that does not exist within the team, `ERR_TRIP_NOT_FOUND` for a `tripId` that does not exist within the team, then `ERR_CONTRACT_NOT_FOUND`, `ERR_LEG_NOT_FOUND`, `ERR_BLOCK_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND` (within the leg's manifest), `ERR_LEDGER_NOT_FOUND` (within the member), `ERR_SHIPMENT_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, or `ERR_CREDENTIAL_NOT_FOUND` as appropriate. An existence failure earlier in the path masks everything later: a request naming a non-existent team never reaches the trip check.

### 2.6. Validation Cascade and Priority Ordering

When several checks guard the same endpoint, the server applies them in a fixed global order, and the first failing check determines the error returned. Request bodies that fail generic shape validation — missing required fields, wrong types — are rejected with `ERR_INVALID_REQUEST` (HTTP 400). The order is:

1. Header presence and shape (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Role authorization (`ERR_INSUFFICIENT_PERMISSIONS`).
3. Path existence, left to right (the 404 family of §2.5).
4. Optimistic concurrency — the `expected_*_version` family (`ERR_STALE_VERSION`).
5. Parent aggregate state: an operation requiring a `DRAFT` trip is rejected with `ERR_TRIP_NOT_DRAFT`; one requiring a `LOCKED` trip with `ERR_TRIP_NOT_LOCKED`; any child mutation on a trip that is already `CLOSED` or `CANCELLED` with `ERR_TRIP_ALREADY_TERMINAL`; any attempt to open new child state under a `CLOSED` season with `ERR_SEASON_CLOSED`; and an operation requiring a hotel block in `NAME_LIST_DUE` with `ERR_BLOCK_NOT_NAME_LIST_DUE`.
6. Target resource state — the state machine preconditions of §3, reported as `ERR_INVALID_STATE` or its specialized variants (`ERR_CONTRACT_NOT_VENDOR_COUNTERSIGNED`, `ERR_LEG_NOT_BOOKED`, `ERR_ENTRY_NOT_PENDING`, `ERR_LEDGER_NOT_APPROVED`, `ERR_CREDENTIAL_NOT_IN_REVIEW`, and similar).
7. The league rest floor (`ERR_REST_FLOOR_VIOLATION`) on leg booking and rebooking.
8. The venue credential gate (`ERR_CREDENTIAL_REQUIRED`) on manifest confirmation.
9. Segregation of duties in the credential workflow (`ERR_SOD_VIOLATION`).
10. Roommate compatibility (`ERR_ROOMMATE_INCOMPATIBLE`).
11. Manifest capacity (`ERR_MANIFEST_FULL`).
12. Charter cargo capacity (`ERR_CARGO_OVERWEIGHT`).
13. The hotel cutoff (`ERR_CUTOFF_PASSED`), guarding room-assignment creation, room confirmation, and block locking.
14. The charter execution window (`ERR_CONTRACT_EXECUTION_WINDOW`).
15. Referenced-target state: a charter leg must reference a contract in `TEAM_EXECUTED` or `ACTIVE` (`ERR_CONTRACT_NOT_EXECUTABLE`), per-diem and credential operations require the member to be `IN` (`ERR_MEMBER_NOT_IN`), and operations that presume a charter leg reject a commercial one (`ERR_LEG_NOT_CHARTER`).
16. Season budget sufficiency (`ERR_BUDGET_EXCEEDED`).
17. Per-diem input shape — `meals_provided_count` and `day_kind` legality (`ERR_INVALID_PER_DIEM_INPUT`).

The practical consequence: on a manifest confirmation, the credential gate is evaluated before the capacity check, so a member lacking venue credentials hears `ERR_CREDENTIAL_REQUIRED` even on a full aircraft; on a room confirmation, roommate compatibility is evaluated before the cutoff check; on an equipment load, the cargo capacity check precedes the referenced-contract state check; and on a charter execution, the 30-day execution window is evaluated before budget sufficiency.

### 2.7. Optimistic Concurrency Control

Three write operations require the caller to prove it has observed the current state of the resource being mutated, by carrying the resource's last-observed `version` as a mandatory request field. Locking a trip requires `expected_trip_version` matching the trip's current `version`; executing a charter contract requires `expected_contract_version` matching the contract's current `version`; and locking a hotel block requires `expected_block_version` matching the block's current `version`. If the supplied value does not match the parent resource's current `version` — because another writer has advanced the resource since the client last read it (a party member added, a leg edited, a vendor counter-signature applied, rooms released) — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no mutation occurs. Endpoints other than these three take no version field.

### 2.8. The Logical Operations Clock

Time-window rules in this domain — the charter execution deadline, contract expiry, hotel name-list milestones, attrition exposure — are evaluated against a logical clock maintained by the server, never the wall clock. At startup the logical clock reads 2026-08-01T00:00:00Z. A `TravelOpsAdmin` may advance it to a supplied instant via the clock-setting capability, passing `to_iso8601`; the capability returns the new `now_utc`. The clock never falls back to wall-clock time, so tests and operations can deterministically walk through a trip's timeline.

### 2.9. Money, Integer Cents, and Rounding

All monetary amounts in the API — budgets, prices, rates, penalties, per-diem amounts, chargebacks, recovery costs — are represented as integer cents. Cost rollups, per-diem arithmetic, attrition penalties, cargo chargebacks, and recovery totals are computed in integer cents with no rounding. The single exception is the charter cancellation penalty, whose percentage arithmetic is rounded half up to a whole cent.

### 2.10. Provisional versus Chronological Cost Accounting

Every trip carries two cost rollups that answer different questions, and they must never be conflated. `estimated_cost_cents` is a provisional, forward-looking projection recomputed on every booking change — at trip lock, charter execution or cancellation, hotel block lock or release, contingency resolution, and equipment loss. `actual_cost_cents` is a chronological ledger replay populated only when the trip closes. Because the two rollups use different inclusion rules, they legitimately diverge: a contingency event still `OPEN` at close was counted in the estimate but is excluded from the actuals, and a per-diem ledger that is `APPROVED` but not yet `PAID` at close was likewise included in the estimate yet contributes nothing to the actuals. Section 3.9 defines both computations in full.

### 2.11. Posture Propagation and Cascade Consistency

A trip's `posture` is derived from the state of its children rather than set directly: it moves from `DRAFT` to `LOCKED` on an explicit lock, from `LOCKED` to `IN_FLIGHT` when the first flight leg departs, into `DISRUPTED` whenever a contingency event opens against a booked leg (whether the trip was `LOCKED` or `IN_FLIGHT`), back to `LOCKED` when every contingency is resolved and every leg is booked again, from `IN_FLIGHT` to `RECOVERING` when the last leg arrives, and finally to `CLOSED` or `CANCELLED`. The server performs these derivations automatically when their criteria are satisfied, without requiring a client request on the trip itself; each such reconciliation mutates the trip (refreshing `updated_at`, incrementing `version`) independently.

Conversely, a mutation that invalidates a parent's assumptions cascades downward: cancelling a trip cancels its contracts, closes its hotel blocks, and adjusts its per-diem drafts; cancelling a charter contract cancels its legs and bumps their manifests; scratching a party member ripples through manifests, rooms, and per-diem. Each cascade is described with its owning workflow in §3, and every resource touched by a cascade has its own `version` incremented.

### 2.12. Season Budget Conservation

A season's `travel_budget_cents` is the hard ceiling on travel spend. The season tracks `committed_cost_cents` — the sum of `estimated_cost_cents` across the season's trips in `LOCKED`, `IN_FLIGHT`, `DISRUPTED`, or `RECOVERING` posture, plus the sum of `actual_cost_cents` across trips in `CLOSED` — and `projected_cost_cents`, which layers provisional estimates from still-open trips on top of the committed figure. The remaining budget is `travel_budget_cents` minus `committed_cost_cents`. Any operation whose proposed change would push committed spend past the ceiling — locking a trip, executing a charter contract, or resolving a contingency with a recovery cost — is rejected with `ERR_BUDGET_EXCEEDED` (HTTP 402). Both season counters start at 0 when the season opens.

## 3. Business Logic & Workflows

### 3.1. Enrolling a Team and Opening a Season

A `TravelOpsAdmin` enrolls an organization by creating a team with a `team_code` (the short league code, such as POR or SEA, unique across all teams), a human-readable `display_name`, and an optional `league_rest_policy` of `STANDARD` or `STRINGENT` that establishes the team's baseline rest rules; when omitted, the policy defaults to `STANDARD`. The team's `active_season_id` remains null until its first season is opened. The team registry can be browsed as a list (with `limit` and `offset`) and filtered by `active_season_id`, and a single team can be fetched by its identifier.

With a team enrolled, a `TravelFinanceLead` opens a season by supplying a `label` (for example, 2026-27) and the season's `travel_budget_cents`. The new season starts in `OPEN` status with `committed_cost_cents` and `projected_cost_cents` at zero, and the team's `active_season_id` pointer is set to it. Seasons are listed under their team, and a flat season list filterable by `team_id` is also available, as is a flat single-season accessor.

Closing a season is the finance lead's final act and is allowed only when every trip in the season has reached `CLOSED` or `CANCELLED` and the season's `projected_cost_cents` equals its `committed_cost_cents` — that is, no open estimates remain anywhere. The transition from `OPEN` to `CLOSED` clears the team's `active_season_id` and increments the season's `version`. Once a season is `CLOSED`, attempts to open new child state under it fail with `ERR_SEASON_CLOSED`.

### 3.2. Building the Trip and the Travel Party

A `TravelManager` creates a trip inside an open season by providing the `season_id`, the destination city's IATA `destination_code`, the scheduled `game_tipoff_utc`, and the planned `return_arrival_utc` back at home base. The trip begins in `DRAFT` posture with `disruption_seq` at 0 — a monotonic counter that every contingency event will increment, giving the operations desk a stable ordering key for rebooking work. Trips are listed under their team with an optional `season_id` filter, and flat trip accessors support `team_id` and `season_id` filters.

The manager then composes the travel party. Each member is added with a roster identifier `member_ref`, a `party_role` drawn from `PLAYER`, `COACH`, `STAFF`, `MEDICAL`, `SECURITY`, `EQUIPMENT`, or `EXECUTIVE`, a `travel_class` of `CHARTER_FIRST`, `CHARTER_STANDARD`, `COMMERCIAL_PREMIUM`, or `COMMERCIAL_COACH`, and a `per_diem_tier` of `TIER_A`, `TIER_B`, or `TIER_C`. Two flags govern logistics downstream: `requires_single_room` (default false) marks a member who must never be assigned a roommate, and `requires_ground_transport` (default true) marks a member who must be counted against ground-leg capacity. Every member carries a system-derived `weight_class` of `LIGHT` or `HEAVY`, computed from their `party_role` and used for equipment-weight chargeback accounting. A member's `status` is `IN`, `OUT`, or `SCRATCHED`; only `IN` members count toward manifests, hotel assignments, and per-diem. The trip's `party_size` is the count of its `IN` members and is recomputed as the roster changes — each roster change also increments the trip's `version`. The roster list accepts a `status` filter, and a flat member list accepts a `trip_id` filter.

When a member can no longer travel, the manager scratches them, moving `status` from `IN` to `SCRATCHED`. Scratching cascades across the trip: every manifest entry for the member is bumped with `bump_reason` `MEDICAL_SCRATCH`, every room assignment of theirs is cancelled, and their draft per-diem ledgers are adjusted; the trip's `version` increments. All roster construction happens while the trip is in `DRAFT`; build-time mutations against a trip that has left `DRAFT` are rejected with `ERR_TRIP_NOT_DRAFT`, and any mutation against a terminal trip with `ERR_TRIP_ALREADY_TERMINAL`.

Locking converts the trip from `DRAFT` to `LOCKED` and is the point of fiscal commitment. A `TravelManager` may lock only when the trip has at least one `IN` party member, the outbound leg (`leg_seq` equal to 1) is in `BOOKED` status, at least one hotel block is in `HOLDING`, `NAME_LIST_DUE`, or `LOCKED` posture, and the trip's `estimated_cost_cents` fits within the season's remaining budget — the `travel_budget_cents` minus `committed_cost_cents` of §2.12. A trip whose estimate exceeds the remaining budget is refused with `ERR_BUDGET_EXCEEDED`. Locking carries the optimistic-concurrency discipline of §2.7 (`expected_trip_version` required). On a successful lock the season's `committed_cost_cents` increases by the trip's `estimated_cost_cents`, the season's `projected_cost_cents` is recomputed, and both the trip's and the season's `version` increment.

### 3.3. Charter Contracting from Draft to Execution

Charter lift is negotiated as a contract per trip. A `TravelManager` drafts a `CharterContract` with the `vendor_code`, the contracted `base_price_cents`, a `fuel_surcharge_cap_cents` bounding what the vendor may bill for fuel, the aircraft's `seat_capacity` and `cargo_capacity_lb`, and the `penalty_bands` — a list of `{days_before, penalty_pct}` entries that must be non-empty and sorted by `days_before` in descending order. A fresh contract is in `DRAFT`.

Submission moves the contract from `DRAFT` to `SUBMITTED`; it is refused unless the `seat_capacity` covers the trip's current `party_size` and the penalty bands satisfy the shape above. The vendor then counter-signs — a `VendorRep` moves `SUBMITTED` to `VENDOR_COUNTERSIGNED` — after which a `TravelFinanceLead` executes the contract on the team's behalf. Execution requires the contract to be `VENDOR_COUNTERSIGNED` (otherwise `ERR_CONTRACT_NOT_VENDOR_COUNTERSIGNED`), the trip still in `DRAFT`, the execution to occur at least 30 days before `game_tipoff_utc` (inside that window the request fails with `ERR_CONTRACT_EXECUTION_WINDOW`), and the season's remaining budget to cover the full exposure of `base_price_cents` plus `fuel_surcharge_cap_cents` (else `ERR_BUDGET_EXCEEDED`). Execution carries the §2.7 discipline via `expected_contract_version`. On execution the contract reaches `TEAM_EXECUTED`, its `executed_at` timestamp is set to the current clock time, the trip's `estimated_cost_cents` increases by the base price plus the fuel surcharge cap, and the trip's `version` increments. When the first flight leg bound to the contract is booked, the contract moves from `TEAM_EXECUTED` to `ACTIVE` on its own. A contract left in `DRAFT` past the execution window — once the logical clock advances beyond 30 days before tipoff — expires to `EXPIRED` without further action.

Cancellation is possible from `DRAFT`, `SUBMITTED`, `VENDOR_COUNTERSIGNED`, or `TEAM_EXECUTED`, provided no flight leg on the contract has `DEPARTED`. The cancellation penalty is computed from the penalty bands: take the whole days remaining until tipoff — the difference between `game_tipoff_utc` and the current clock time, discarding any partial day — and select the first band in the descending `days_before` ordering whose threshold has been reached (the band's `days_before` is less than or equal to the days remaining). If no band matches because the cancellation falls after even the earliest threshold, the penalty percentage is 100. The `cancellation_penalty_cents` is that percentage of the sum of `base_price_cents` and `fuel_surcharge_cap_cents`, rounded half up to a whole cent. Cancelling stamps `cancelled_at`, reduces the trip's `estimated_cost_cents` by the base price plus fuel cap minus the penalty (the penalty remains as cost exposure), cancels every flight leg bound to the contract, and bumps every manifest entry on those legs with `bump_reason` `OVERBOOK`. Contracts are listed under their trip, a dedicated listing shows the flight legs bound to a specific contract, and flat contract accessors support a `trip_id` filter.

### 3.4. Flight Legs, Booking, and the League Rest Floor

A `TravelCoordinator` lays out the trip's flying as a sequence of legs, each with a `leg_seq` (1 for the outbound), `origin_code` and `destination_code` IATA codes, planned `scheduled_depart_utc` and `scheduled_arrive_utc`, and an `is_charter` flag. A charter leg must reference its contract via `contract_id` — required exactly when `is_charter` is true — while a commercial leg carries none. Each new leg starts `PLANNED` with `rebook_generation` at 0, `delay_minutes` at 0 until arrival, and `actual_depart_utc` / `actual_arrive_utc` unset; creating a leg increments the trip's `version`. Legs are listed under their trip with `status` and `contract_id` filters, and flat leg accessors support `trip_id` and `contract_id` filters.

Booking moves a leg from `PLANNED` to `BOOKED` and enforces three rules. First, a charter leg's contract must be in `TEAM_EXECUTED` or `ACTIVE` (otherwise `ERR_CONTRACT_NOT_EXECUTABLE`; referencing a commercial arrangement where a charter is expected fails with `ERR_LEG_NOT_CHARTER`). Second, the league rest floor: for any leg with `leg_seq` greater than 1, the planned `scheduled_depart_utc` must be no earlier than the prior leg's `scheduled_arrive_utc` plus the required rest minutes. The required rest is a base of 600 minutes under a `STANDARD` `league_rest_policy` or 720 minutes under `STRINGENT`, plus a delay compounding term — for every full sixty minutes by which the prior leg's `delay_minutes` exceeds its first hour, an additional 60 minutes under `STANDARD` or 90 minutes under `STRINGENT`. A departure inside the floor is rejected with `ERR_REST_FLOOR_VIOLATION`. Third, for charter legs, the manifest capacity check of §3.5: the count of `IN` travel party members must not exceed the contract's `seat_capacity`. Booking the first leg on a `TEAM_EXECUTED` contract flips the contract to `ACTIVE`, and each booking increments the trip's `version`.

Irregular operations are first-class. Reporting a delay on a `BOOKED` leg (with a positive `delay_minutes`, else the request is invalid; a leg not in `BOOKED` yields `ERR_LEG_NOT_BOOKED`) moves it to `DELAYED`, pushes `scheduled_arrive_utc` later by the delay, and forces every downstream leg whose scheduled departure now falls before the new arrival plus the rest floor into `REBOOKING`. Rebooking — from either `DELAYED` or `REBOOKING` — returns the leg to `BOOKED` with a rewritten `scheduled_depart_utc` and `scheduled_arrive_utc`; the new departure must again satisfy the rest floor against the prior leg, and when rebooking from `DELAYED` the charter contract must still have seat capacity for the `IN` members. Each rebooking increments the leg's `rebook_generation` (used to tie-break manifest reconciliation), keeps the manifest entries in place, and resets every entry's `is_ticketed` to false; rebooking from `DELAYED` also increments the trip's `version`.

Departure requires every manifest entry still in `PENDING` to have been resolved one way or the other — confirmed or bumped — and then moves the leg from `BOOKED` to `DEPARTED`, stamping `actual_depart_utc` with the current clock time. If the departing leg is the trip's first, the trip's posture moves from `LOCKED` to `IN_FLIGHT`. Marking arrival moves the leg from `DEPARTED` to `ARRIVED`: it stamps `actual_arrive_utc`, computes `delay_minutes` as the difference between actual and scheduled arrival in minutes, moves all `CONFIRMED` manifest entries to `FLOWN`, and — when the arriving leg is the trip's last — moves the trip from `IN_FLIGHT` to `RECOVERING`. A leg in `PLANNED`, `BOOKED`, `DELAYED`, or `REBOOKING` may also be cancelled outright; its manifest entries are moved to `BUMPED` with `bump_reason` `OVERBOOK`, and if it was a charter leg and no non-cancelled legs remain on the contract, the contract stays `ACTIVE` with the trip estimate unchanged — penalties are handled at the contract level, not the leg level.

### 3.5. Manifests, Bumping, and the Venue Credential Gate

For each leg, the `TravelCoordinator` builds the manifest by adding an entry per travelling member — a payload carrying the `member_id` and, for charter flying, a `seat_assignment` label such as 1A; the seat may be left null for commercial unticketed travel. New entries are `PENDING` with `is_ticketed` false. Entries are listed per leg (filterable by `member_id`) and per member across the trip's legs; flat manifest accessors accept `flight_leg_id` and `member_id` filters.

Confirmation moves an entry from `PENDING` to `CONFIRMED` and sets `is_ticketed` true; an entry not in `PENDING` yields `ERR_ENTRY_NOT_PENDING`. Three gates guard confirmation. The member must still be `IN` (else `ERR_MEMBER_NOT_IN`). The leg must be in `BOOKED` or `DELAYED`. And the venue credential gate: when the leg's destination requires a venue credential, the member must hold an `APPROVED` credential request for the trip, or the confirmation is rejected with `ERR_CREDENTIAL_REQUIRED`. Capacity is enforced for charter legs throughout: at booking time the count of entries in `PENDING` or `CONFIRMED` must not exceed the contract's `seat_capacity`, and at confirmation time the count of `CONFIRMED` entries must be strictly below `seat_capacity` — when the confirmed count equals `seat_capacity` minus one, exactly one more confirmation succeeds, and once the confirmed count equals `seat_capacity`, the next confirmation fails with `ERR_MANIFEST_FULL`.

Entries leave the manifest in several ways. The coordinator may bump a `CONFIRMED` entry to `BUMPED`, recording a `bump_reason` of `OVERBOOK`, `WEIGHT_BALANCE`, `SECURITY_DENIAL`, or `MEDICAL_SCRATCH`. System events bump entries too: a cancelled leg or cancelled charter contract moves its `PENDING` entries to `BUMPED` with `OVERBOOK`, a scratched member's entries are bumped with `MEDICAL_SCRATCH`, and a denied or revoked credential bumps the member's `CONFIRMED` entries on legs to that venue to `BUMPED` with `SECURITY_DENIAL`. If a leg departs without a `CONFIRMED` member being scanned aboard, the entry becomes `NO_SHOW`; entries still `CONFIRMED` when the leg arrives become `FLOWN`.

### 3.6. Hotel Blocks and Room Assignment Discipline

Ground lodging is contracted per trip as hotel blocks. A `TravelCoordinator` creates a block with the `hotel_code`, the contracted `room_count`, the `rate_cents_per_night`, the `check_in_date` of the first night, the `night_count` of consecutive nights, the `cutoff_date` after which room names may no longer be submitted to the hotel, and an optional `attrition_allowance_pct` — the slippage percentage the hotel tolerates before penalties apply, defaulting to 10. A new block is `HOLDING` with `rooms_released` at 0, and creating one increments the trip's `version`. Blocks are listed under their trip, with flat accessors filterable by `trip_id`.

The block's calendar is driven by the logical clock. Seven days before `cutoff_date`, the block moves from `HOLDING` to `NAME_LIST_DUE` — the signal that the rooming list must be finalized. If the clock reaches `cutoff_date` with occupancy below the attrition allowance, the block becomes `ATTRITION_EXPOSED` and a penalty lands on the trip's `estimated_cost_cents`. The attrition arithmetic: allowed slippage is `room_count` multiplied by `attrition_allowance_pct` and divided by 100, rounded down to whole rooms; occupied rooms are the assignments in `CONFIRMED`, `CHECKED_IN`, or `CHECKED_OUT`; penalty rooms are `room_count` minus `rooms_released` minus occupied rooms minus allowed slippage, floored at zero; and each penalty room costs `rate_cents_per_night` multiplied by `night_count`.

Locking the block — `NAME_LIST_DUE` to `LOCKED`, by the coordinator, carrying the §2.7 `expected_block_version` — certifies the rooming list. It requires that every `IN` member flagged `requires_single_room` holds an assignment with a null `roommate_member_id`, that every `IN` member holds at least one non-`CANCELLED` assignment in this block or a sibling block on the same trip, and that the count of non-`CANCELLED` assignments is at least `room_count` minus `rooms_released` minus the attrition floor (the allowed-slippage figure above). A block in the wrong posture is refused with `ERR_BLOCK_NOT_NAME_LIST_DUE`, and once `cutoff_date` has passed, room-name changes — creating or confirming assignments — and locking are all rejected with `ERR_CUTOFF_PASSED`. Locking increments the trip's `version`. After checkout day passes, both `LOCKED` and `ATTRITION_EXPOSED` blocks close to `CLOSED` automatically.

Rooms may be handed back to the hotel before lock via a release carrying `rooms_to_release`, provided no assignment in the block is currently `CHECKED_IN`. Releasing increments `rooms_released` accordingly, reduces the trip's `estimated_cost_cents` by the released rooms' nightly rate times the night count, and may tip the block into `ATTRITION_EXPOSED` when occupancy falls below the allowance. Releasing a `HOLDING` or `NAME_LIST_DUE` block entirely closes it: `rooms_released` becomes `room_count` minus the occupied rooms, and every non-terminal assignment in the block is cancelled.

Individual rooms are managed as assignments within a block. Creating one takes the `member_id`, an optional `roommate_member_id` (null for singles), a `room_label`, and an optional `smoking_pref` defaulting to false; the assignment starts `RESERVED`. Confirming an assignment requires the member to be `IN` and, when a roommate is named, the roommate must also be `IN`, must not be flagged `requires_single_room`, and must have a `party_role` in the same rooming group as the primary member's — a member flagged `requires_single_room` may never be assigned a roommate at all. Compatibility failures are rejected with `ERR_ROOMMATE_INCOMPATIBLE`. Confirmation stamps `confirmed_at`. Check-in moves a `CONFIRMED` assignment to `CHECKED_IN` and is only possible once the block is `LOCKED`; checkout moves it to `CHECKED_OUT`. An assignment in `RESERVED` or `CONFIRMED` may be cancelled — and when a cancelled assignment belonged to a `requires_single_room` member who was its sole occupant, the block's occupancy counter decrements accordingly. Assignments are listed per block (filterable by `member_id` or `roommate_member_id`) and per member, with flat accessors accepting `hotel_block_id`, `member_id`, and `roommate_member_id` filters.

### 3.7. Equipment Shipments and Cargo Chargebacks

The `EquipmentManager` registers each shipment with a `shipment_kind` of `TEAM_GEAR`, `MEDICAL`, `BROADCAST`, or `PERSONAL_BAGGAGE`, its `gross_weight_lb`, a `piece_count` of crates or bags, and a `declared_value_cents` for insurance. A shipment may name the `assigned_contract_id` of the charter carrying it; ground-only shipments leave it null. Shipments start `STAGED` with `chargeback_cents` at 0, and are listed per trip (filterable by `assigned_contract_id`), per contract, or via flat accessors with `trip_id` and `assigned_contract_id` filters.

Loading a shipment onto its charter moves it from `STAGED` to `LOADED` and enforces the cargo ceiling: the referenced contract must be `ACTIVE`, and the cumulative `gross_weight_lb` of all non-lost shipments on the contract, this shipment included, must not exceed the contract's `cargo_capacity_lb` — an overload is rejected with `ERR_CARGO_OVERWEIGHT`. Loading also computes the tiered weight-overage chargeback against the total committed weight on the contract including this shipment. Weight up to and including 85 percent of `cargo_capacity_lb` is free — the 85-percent boundary itself is 85 percent of capacity rounded down to a whole pound. Committed weight in the band above that boundary and up to the full capacity is charged 350 cents per pound. Any committed weight beyond full capacity is charged 900 cents per pound, on top of the 350-cents-per-pound charge across the entire 85-to-100-percent slice. The shipment's `chargeback_cents` is the sum of the two tier charges. Loading increments the trip's `version`.

Thereafter the shipment rides the leg's fate: when the associated leg departs, the shipment moves from `LOADED` to `IN_TRANSIT`; a leg delay moves it to `DELAYED`, and a rebooked departure returns it to `IN_TRANSIT`. Delivery is recorded by the equipment manager as `DELIVERED`. If the shipment goes missing, marking it lost — allowed from `STAGED`, `LOADED`, `IN_TRANSIT`, or `DELAYED` — sets `chargeback_cents` to the full `declared_value_cents` as an insurance claim and adds that amount to the trip's `estimated_cost_cents`.

### 3.8. Per-Diem Ledgers and Meal Deductions

Per-diem is administered per member per day. A `TravelFinanceLead` creates a ledger row with the `service_date` it covers, a `day_kind` of `TRAVEL_DAY`, `GAME_DAY`, `OFF_DAY`, or `PARTIAL_DAY`, and an optional `meals_provided_count` — the number of team-provided meals that day, defaulting to 0 and capped at 3; a count above 3 or an unrecognized `day_kind` is rejected with `ERR_INVALID_PER_DIEM_INPUT` (HTTP 400). The row's money fields are computed at creation from the member's `per_diem_tier`. The base rate — a `TIER_A` member draws 12,000 cents on a `TRAVEL_DAY`, 15,000 on a `GAME_DAY`, 9,000 on an `OFF_DAY`, and 6,000 on a `PARTIAL_DAY`; the `TIER_B` schedule pays 9,000, 11,000, 7,000, and 4,500 cents across the same four day kinds; and `TIER_C` pays 6,500, 8,000, 5,000, and 3,250 cents respectively — becomes `base_amount_cents`. Each team-provided meal deducts a flat 2,500 cents, so `deduction_cents` is `meals_provided_count` times 2,500, and `net_amount_cents` is the base minus the deduction, floored at zero. New rows are `DRAFT` and are listed per member, with flat accessors filterable by `member_id`.

Approval by the finance lead requires the member to have been `IN` on the ledger's `service_date` (otherwise `ERR_MEMBER_NOT_IN`) and increments the trip's `version`. Payment moves an `APPROVED` row to `PAID` — anything else yields `ERR_LEDGER_NOT_APPROVED` — provided the trip is in `LOCKED`, `IN_FLIGHT`, `RECOVERING`, or `DISRUPTED` posture, and stamps `paid_at` with the current clock time while incrementing the trip's `version`. A `TeamMember` who disagrees with a row may dispute it, moving `APPROVED` to `DISPUTED`; the finance lead resolves the dispute by supplying a corrected `meals_provided_count` — subject to the same three-meal cap and `ERR_INVALID_PER_DIEM_INPUT` rejection — which recomputes the deduction and the `net_amount_cents` and returns the row to `APPROVED`. Finally, if the trip itself is cancelled, every ledger row still in `DRAFT` is swept to `ADJUSTED` with its `net_amount_cents` zeroed out.

### 3.9. Disruptions, Recovery, Cancellation, and Close-Out

When operations observes trouble — a `kind` of `WEATHER`, `MECHANICAL`, `ATC_DELAY`, `VENUE_CHANGE`, or `SECURITY_INCIDENT` — a `TravelManager` opens a contingency event with the `detected_at` timestamp, the `affected_leg_id`, and a `severity` of `MINOR`, `MAJOR`, or `CRITICAL`. The event opens in `OPEN` status; the trip's `disruption_seq` increments; and if the trip was `LOCKED` or `IN_FLIGHT`, its posture becomes `DISRUPTED`. Note the asymmetry between the two entry paths: opening an event against a booked leg of a `LOCKED` trip also pushes the affected leg into `REBOOKING`, while an event opened mid-flight (`IN_FLIGHT`) only increments the disruption counter — aircraft already airborne are not sent back to booking. Either way the trip's `version` increments. Events are listed per trip (filterable by `affected_leg_id`), per leg, or via flat accessors with `trip_id` and `affected_leg_id` filters.

Working the event is a two-step desk process. Mitigation selects a `resolution_action` of `REBOOK`, `REROUTE`, `OVERNIGHT`, `CANCEL_TRIP`, or `NONE` and moves the event to `MITIGATING`. Resolution then moves it to `RESOLVED` and records the `recovery_cost_cents` incurred; the preconditions depend on the chosen action — a `REBOOK` resolution requires the affected leg to be back in `BOOKED`, and an `OVERNIGHT` resolution requires a hotel block covering the disruption night to exist. Resolving adds the recovery cost to the trip's `estimated_cost_cents` — subject to the season budget ceiling, so a resolution that would breach it is rejected with `ERR_BUDGET_EXCEEDED` — and re-evaluates the trip's posture: once no event remains in `OPEN` or `MITIGATING` and no leg remains in `REBOOKING`, a `DISRUPTED` trip returns to `LOCKED`, the season's `projected_cost_cents` is adjusted by the sum of the events' `recovery_cost_cents`, and both trip and season versions increment. An event whose affected leg was cancelled, or whose whole trip was cancelled, may instead be closed without action, moving `OPEN` straight to `CLOSED`.

Cancellation of the trip itself comes in two flavors. From `DRAFT`, cancellation simply moves the trip to `CANCELLED` with no change to the season's `committed_cost_cents` — the trip was never locked, so nothing was ever committed. From `DISRUPTED`, cancellation is permitted only while no leg has `DEPARTED`, and it unwinds the whole trip: every charter contract in `SUBMITTED`, `VENDOR_COUNTERSIGNED`, `TEAM_EXECUTED`, or `ACTIVE` is cancelled with its `cancellation_penalty_cents` computed from the penalty bands as in §3.3; every hotel block closes with `rooms_released` set to `room_count` minus the occupied rooms; every per-diem row still in `DRAFT` is adjusted to zero; and the season's `committed_cost_cents` is reduced by the trip's `estimated_cost_cents` less whatever actual costs have already been incurred. The trip, the season, and every cancelled child each increment their `version`.

Close-out begins once the last leg has arrived and the trip sits in `RECOVERING`. A `TravelFinanceLead` may close the trip only when every equipment shipment is `DELIVERED` or `LOST`, every per-diem row is `PAID` or `ADJUSTED`, every credential request is `APPROVED`, `DENIED`, or `REVOKED`, and every contingency event is `RESOLVED` or `CLOSED`. Closing computes the trip's `actual_cost_cents` as a chronological ledger replay: the trip's financial events are replayed in order of their event timestamps (ties broken by creation time), with each charter execution contributing its base price plus fuel surcharge cap; each charter cancellation removing the base and cap and contributing only its penalty; each hotel block lock contributing the un-released rooms' rate times nights; each attrition exposure contributing its penalty; each per-diem payment contributing the `net_amount_cents` as of pay time; each equipment loss contributing its `chargeback_cents`; and each contingency resolution contributing its `recovery_cost_cents`. The running sum is the actual cost. The season's `committed_cost_cents` is then adjusted to replace the trip's estimate with its actual, and `projected_cost_cents` is recomputed.

This is where the two accounting lenses of §2.10 diverge by design. The forward-looking `estimated_cost_cents` at lock time counts every `DRAFT` per-diem row at its full `base_amount_cents` regardless of `meals_provided_count` — a deliberately conservative assumption of zero team-provided meals — while the close-out replay uses the actual meal counts; the estimate counts charter contracts at their full base-plus-cap exposure while cancelled contracts contribute only their penalty to the actuals; and anything still unresolved at close — an `OPEN` contingency, an `APPROVED`-but-unpaid per-diem row — was in the estimate but is excluded from the actuals. At any moment, the estimate itself is maintained as the sum of five components: the base price plus fuel surcharge cap minus any penalty already charged, across contracts in `TEAM_EXECUTED` or `ACTIVE`; the un-released rooms' rate times nights across blocks in `HOLDING`, `NAME_LIST_DUE`, `LOCKED`, or `ATTRITION_EXPOSED`; the `chargeback_cents` of shipments in `STAGED`, `LOADED`, `IN_TRANSIT`, `DELAYED`, or `LOST`; the `net_amount_cents` of per-diem rows in `DRAFT`, `APPROVED`, or `PAID` belonging to `IN` members; and the `recovery_cost_cents` of contingency events in `OPEN`, `MITIGATING`, or `RESOLVED`.

### 3.10. Venue Credentials and Segregation of Duties

Venue access is credentialed per member per trip. A `TeamMember` submits a credential request naming the `member_id`, the `venue_code`, and an `access_level` of `FIELD`, `LOCKER_ROOM`, `PRESS`, `BACK_OF_HOUSE`, or `ALL_ACCESS`; the request starts in `SUBMITTED` with the acting user's `X-User-ID` recorded as `submitted_by_user_id`. Requests are listed per trip or per member (both filterable by `member_id`), with flat accessors supporting `trip_id` and `member_id` filters.

Review is a two-person chain enforced by segregation of duties. A `SecurityOfficer` moves the request from `SUBMITTED` to `SECURITY_REVIEW`, but only if the officer's `X-User-ID` differs from the `submitted_by_user_id` — a submitter may not review their own request, and the attempt fails with `ERR_SOD_VIOLATION` (HTTP 403); the officer's identity is recorded as `reviewed_by_user_id`. A `VenueCredentialApprover` then acts on a request in `SECURITY_REVIEW` (anything else yields `ERR_CREDENTIAL_NOT_IN_REVIEW`). Approval requires the approver's `X-User-ID` to differ from both the submitter's and the reviewer's — again `ERR_SOD_VIOLATION` on a clash — records `approved_by_user_id`, moves the request to `APPROVED`, and lifts the manifest gate of §3.5: any `PENDING` manifest entry for that member on legs to that venue may now confirm. Denial requires a `denial_reason` (the field is required exactly when the status is `DENIED`), moves the request to `DENIED`, and bumps every `CONFIRMED` manifest entry for that member on legs to that venue with `bump_reason` `SECURITY_DENIAL`. An approved credential may later be revoked by a `SecurityOfficer`; revocation moves `APPROVED` to `REVOKED` and applies the same manifest bump cascade with `SECURITY_DENIAL`.

## 4. Endpoint Definitions

Operations that create a new resource — a team, season, trip, party member, charter contract, flight leg, manifest entry, hotel block, room assignment, per-diem row, equipment shipment, contingency event, or credential request — return `201 Created`. Operations that modify an existing resource, including every state-transition action, return `200 OK`. All endpoints are mounted under the `/travel` prefix.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/travel/_clock/set_current_utc` | Advance the logical clock | TravelOpsAdmin |
| POST | `/travel/teams` | Create a team | TravelOpsAdmin |
| GET | `/travel/teams` | List teams | Any |
| GET | `/travel/teams/{teamId}` | Get a team | Any |
| POST | `/travel/teams/{teamId}/seasons` | Open a new season | TravelFinanceLead |
| GET | `/travel/teams/{teamId}/seasons` | List seasons for a team | Any |
| GET | `/travel/teams/{teamId}/seasons/{seasonId}` | Get a season | Any |
| POST | `/travel/teams/{teamId}/seasons/{seasonId}/close` | Close a season | TravelFinanceLead |
| POST | `/travel/teams/{teamId}/trips` | Create a trip in DRAFT | TravelManager |
| GET | `/travel/teams/{teamId}/trips` | List trips for a team | Any |
| GET | `/travel/teams/{teamId}/trips/{tripId}` | Get a trip | Any |
| POST | `/travel/teams/{teamId}/trips/{tripId}/lock` | Lock trip (DRAFT to LOCKED) | TravelManager |
| POST | `/travel/teams/{teamId}/trips/{tripId}/close` | Close trip (RECOVERING to CLOSED) | TravelFinanceLead |
| POST | `/travel/teams/{teamId}/trips/{tripId}/cancel` | Cancel a trip | TravelManager |
| POST | `/travel/teams/{teamId}/trips/{tripId}/members` | Add a party member | TravelManager |
| GET | `/travel/teams/{teamId}/trips/{tripId}/members` | List members of a trip | Any |
| GET | `/travel/teams/{teamId}/trips/{tripId}/members/{memberId}` | Get a member | Any |
| POST | `/travel/teams/{teamId}/trips/{tripId}/members/{memberId}/scratch` | Scratch member (IN to SCRATCHED) | TravelManager |
| POST | `/travel/teams/{teamId}/trips/{tripId}/charter-contracts` | Draft a charter contract | TravelManager |
| GET | `/travel/teams/{teamId}/trips/{tripId}/charter-contracts` | List charter contracts for a trip | Any |
| GET | `/travel/teams/{teamId}/trips/{tripId}/charter-contracts/{contractId}` | Get a contract | Any |
| POST | `/travel/teams/{teamId}/trips/{tripId}/charter-contracts/{contractId}/submit` | Submit contract to vendor | TravelManager |
| POST | `/travel/teams/{teamId}/trips/{tripId}/charter-contracts/{contractId}/countersign` | Vendor counter-signs | VendorRep |
| POST | `/travel/teams/{teamId}/trips/{tripId}/charter-contracts/{contractId}/execute` | Team executes contract | TravelFinanceLead |
| POST | `/travel/teams/{teamId}/trips/{tripId}/charter-contracts/{contractId}/cancel` | Cancel contract | TravelManager |
| POST | `/travel/teams/{teamId}/trips/{tripId}/flight-legs` | Add a flight leg | TravelCoordinator |
| GET | `/travel/teams/{teamId}/trips/{tripId}/flight-legs` | List legs of a trip | Any |
| GET | `/travel/teams/{teamId}/trips/{tripId}/flight-legs/{legId}` | Get a leg | Any |
| GET | `/travel/teams/{teamId}/trips/{tripId}/charter-contracts/{contractId}/flight-legs` | List legs bound to a contract | Any |
| POST | `/travel/teams/{teamId}/trips/{tripId}/flight-legs/{legId}/book` | Book a leg | TravelCoordinator |
| POST | `/travel/teams/{teamId}/trips/{tripId}/flight-legs/{legId}/delay` | Report a delay on a booked leg | TravelCoordinator |
| POST | `/travel/teams/{teamId}/trips/{tripId}/flight-legs/{legId}/rebook` | Rebook a delayed/rebooking leg | TravelCoordinator |
| POST | `/travel/teams/{teamId}/trips/{tripId}/flight-legs/{legId}/depart` | Mark leg departed | TravelCoordinator |
| POST | `/travel/teams/{teamId}/trips/{tripId}/flight-legs/{legId}/arrive` | Mark leg arrived | TravelCoordinator |
| POST | `/travel/teams/{teamId}/trips/{tripId}/flight-legs/{legId}/cancel` | Cancel a leg | TravelCoordinator |
| POST | `/travel/teams/{teamId}/trips/{tripId}/flight-legs/{legId}/manifest` | Add a manifest entry | TravelCoordinator |
| GET | `/travel/teams/{teamId}/trips/{tripId}/flight-legs/{legId}/manifest` | List manifest entries on a leg | Any |
| GET | `/travel/teams/{teamId}/trips/{tripId}/flight-legs/{legId}/manifest/{entryId}` | Get a manifest entry | Any |
| GET | `/travel/teams/{teamId}/trips/{tripId}/members/{memberId}/manifest` | List manifest entries for a member | Any |
| POST | `/travel/teams/{teamId}/trips/{tripId}/flight-legs/{legId}/manifest/{entryId}/confirm` | Confirm manifest entry | TravelCoordinator |
| POST | `/travel/teams/{teamId}/trips/{tripId}/flight-legs/{legId}/manifest/{entryId}/bump` | Bump an entry | TravelCoordinator |
| POST | `/travel/teams/{teamId}/trips/{tripId}/hotel-blocks` | Create a hotel block | TravelCoordinator |
| GET | `/travel/teams/{teamId}/trips/{tripId}/hotel-blocks` | List hotel blocks for a trip | Any |
| GET | `/travel/teams/{teamId}/trips/{tripId}/hotel-blocks/{blockId}` | Get a hotel block | Any |
| POST | `/travel/teams/{teamId}/trips/{tripId}/hotel-blocks/{blockId}/lock` | Lock hotel block | TravelCoordinator |
| POST | `/travel/teams/{teamId}/trips/{tripId}/hotel-blocks/{blockId}/release` | Release rooms back to hotel | TravelCoordinator |
| POST | `/travel/teams/{teamId}/trips/{tripId}/hotel-blocks/{blockId}/rooms` | Create a room assignment | TravelCoordinator |
| GET | `/travel/teams/{teamId}/trips/{tripId}/hotel-blocks/{blockId}/rooms` | List room assignments in a block | Any |
| GET | `/travel/teams/{teamId}/trips/{tripId}/hotel-blocks/{blockId}/rooms/{roomId}` | Get a room assignment | Any |
| GET | `/travel/teams/{teamId}/trips/{tripId}/members/{memberId}/rooms` | List room assignments for a member | Any |
| POST | `/travel/teams/{teamId}/trips/{tripId}/hotel-blocks/{blockId}/rooms/{roomId}/confirm` | Confirm a room assignment | TravelCoordinator |
| POST | `/travel/teams/{teamId}/trips/{tripId}/hotel-blocks/{blockId}/rooms/{roomId}/checkin` | Check in | TravelCoordinator |
| POST | `/travel/teams/{teamId}/trips/{tripId}/hotel-blocks/{blockId}/rooms/{roomId}/checkout` | Check out | TravelCoordinator |
| POST | `/travel/teams/{teamId}/trips/{tripId}/hotel-blocks/{blockId}/rooms/{roomId}/cancel` | Cancel a room assignment | TravelCoordinator |
| POST | `/travel/teams/{teamId}/trips/{tripId}/members/{memberId}/per-diem` | Create a per-diem ledger entry | TravelFinanceLead |
| GET | `/travel/teams/{teamId}/trips/{tripId}/members/{memberId}/per-diem` | List per-diem entries for a member | Any |
| GET | `/travel/teams/{teamId}/trips/{tripId}/members/{memberId}/per-diem/{ledgerId}` | Get a ledger entry | Any |
| POST | `/travel/teams/{teamId}/trips/{tripId}/members/{memberId}/per-diem/{ledgerId}/approve` | Approve ledger | TravelFinanceLead |
| POST | `/travel/teams/{teamId}/trips/{tripId}/members/{memberId}/per-diem/{ledgerId}/pay` | Pay ledger | TravelFinanceLead |
| POST | `/travel/teams/{teamId}/trips/{tripId}/members/{memberId}/per-diem/{ledgerId}/dispute` | Dispute ledger | TeamMember |
| POST | `/travel/teams/{teamId}/trips/{tripId}/members/{memberId}/per-diem/{ledgerId}/resolve` | Resolve a disputed ledger | TravelFinanceLead |
| POST | `/travel/teams/{teamId}/trips/{tripId}/equipment` | Create an equipment shipment | EquipmentManager |
| GET | `/travel/teams/{teamId}/trips/{tripId}/equipment` | List equipment shipments for a trip | Any |
| GET | `/travel/teams/{teamId}/trips/{tripId}/equipment/{shipmentId}` | Get a shipment | Any |
| GET | `/travel/teams/{teamId}/trips/{tripId}/charter-contracts/{contractId}/equipment` | List shipments assigned to a contract | Any |
| POST | `/travel/teams/{teamId}/trips/{tripId}/equipment/{shipmentId}/load` | Load shipment onto charter | EquipmentManager |
| POST | `/travel/teams/{teamId}/trips/{tripId}/equipment/{shipmentId}/deliver` | Mark shipment delivered | EquipmentManager |
| POST | `/travel/teams/{teamId}/trips/{tripId}/equipment/{shipmentId}/mark-lost` | Mark shipment lost | EquipmentManager |
| POST | `/travel/teams/{teamId}/trips/{tripId}/contingencies` | Open a contingency event | TravelManager |
| GET | `/travel/teams/{teamId}/trips/{tripId}/contingencies` | List contingency events for a trip | Any |
| GET | `/travel/teams/{teamId}/trips/{tripId}/contingencies/{eventId}` | Get a contingency | Any |
| GET | `/travel/teams/{teamId}/trips/{tripId}/flight-legs/{legId}/contingencies` | List contingencies affecting a leg | Any |
| POST | `/travel/teams/{teamId}/trips/{tripId}/contingencies/{eventId}/mitigate` | Select a mitigation action | TravelManager |
| POST | `/travel/teams/{teamId}/trips/{tripId}/contingencies/{eventId}/resolve` | Resolve contingency | TravelManager |
| POST | `/travel/teams/{teamId}/trips/{tripId}/contingencies/{eventId}/close-noop` | Close contingency without action | TravelManager |
| POST | `/travel/teams/{teamId}/trips/{tripId}/credentials` | Submit credential request | TeamMember |
| GET | `/travel/teams/{teamId}/trips/{tripId}/credentials` | List credentials for a trip | Any |
| GET | `/travel/teams/{teamId}/trips/{tripId}/credentials/{credId}` | Get a credential | Any |
| GET | `/travel/teams/{teamId}/trips/{tripId}/members/{memberId}/credentials` | List credentials for a member | Any |
| POST | `/travel/teams/{teamId}/trips/{tripId}/credentials/{credId}/security-review` | Move credential to security review | SecurityOfficer |
| POST | `/travel/teams/{teamId}/trips/{tripId}/credentials/{credId}/approve` | Approve credential | VenueCredentialApprover |
| POST | `/travel/teams/{teamId}/trips/{tripId}/credentials/{credId}/deny` | Deny credential | VenueCredentialApprover |
| POST | `/travel/teams/{teamId}/trips/{tripId}/credentials/{credId}/revoke` | Revoke an approved credential | SecurityOfficer |
| GET | `/travel/seasons/{id}` | Get a season by id (flat accessor) | Any |
| GET | `/travel/seasons` | List seasons (flat) | Any |
| GET | `/travel/trips/{id}` | Get a trip by id (flat accessor) | Any |
| GET | `/travel/trips` | List trips (flat) | Any |
| GET | `/travel/members/{id}` | Get a member by id (flat accessor) | Any |
| GET | `/travel/members` | List members (flat) | Any |
| GET | `/travel/charter-contracts/{id}` | Get a charter contract by id (flat accessor) | Any |
| GET | `/travel/charter-contracts` | List charter contracts (flat) | Any |
| GET | `/travel/flight-legs/{id}` | Get a flight leg by id (flat accessor) | Any |
| GET | `/travel/flight-legs` | List flight legs (flat) | Any |
| GET | `/travel/manifest-entries/{id}` | Get a manifest entry by id (flat accessor) | Any |
| GET | `/travel/manifest-entries` | List manifest entries (flat) | Any |
| GET | `/travel/hotel-blocks/{id}` | Get a hotel block by id (flat accessor) | Any |
| GET | `/travel/hotel-blocks` | List hotel blocks (flat) | Any |
| GET | `/travel/rooms/{id}` | Get a room assignment by id (flat accessor) | Any |
| GET | `/travel/rooms` | List room assignments (flat) | Any |
| GET | `/travel/per-diem/{id}` | Get a per-diem ledger by id (flat accessor) | Any |
| GET | `/travel/per-diem` | List per-diem ledgers (flat) | Any |
| GET | `/travel/equipment/{id}` | Get an equipment shipment by id (flat accessor) | Any |
| GET | `/travel/equipment` | List equipment shipments (flat) | Any |
| GET | `/travel/contingencies/{id}` | Get a contingency event by id (flat accessor) | Any |
| GET | `/travel/contingencies` | List contingencies (flat) | Any |
| GET | `/travel/credentials/{id}` | Get a credential request by id (flat accessor) | Any |
| GET | `/travel/credentials` | List credentials (flat) | Any |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_TEAM_NOT_FOUND` | 404 Not Found |
| `ERR_SEASON_NOT_FOUND` | 404 Not Found |
| `ERR_TRIP_NOT_FOUND` | 404 Not Found |
| `ERR_LEG_NOT_FOUND` | 404 Not Found |
| `ERR_CONTRACT_NOT_FOUND` | 404 Not Found |
| `ERR_BLOCK_NOT_FOUND` | 404 Not Found |
| `ERR_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_ENTRY_NOT_FOUND` | 404 Not Found |
| `ERR_LEDGER_NOT_FOUND` | 404 Not Found |
| `ERR_SHIPMENT_NOT_FOUND` | 404 Not Found |
| `ERR_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_CREDENTIAL_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_TRIP_NOT_DRAFT` | 409 Conflict |
| `ERR_TRIP_NOT_LOCKED` | 409 Conflict |
| `ERR_TRIP_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_SEASON_CLOSED` | 409 Conflict |
| `ERR_BLOCK_NOT_NAME_LIST_DUE` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CONTRACT_NOT_VENDOR_COUNTERSIGNED` | 409 Conflict |
| `ERR_CONTRACT_NOT_EXECUTABLE` | 409 Conflict |
| `ERR_LEG_NOT_BOOKED` | 409 Conflict |
| `ERR_ENTRY_NOT_PENDING` | 409 Conflict |
| `ERR_LEDGER_NOT_APPROVED` | 409 Conflict |
| `ERR_CREDENTIAL_NOT_IN_REVIEW` | 409 Conflict |
| `ERR_REST_FLOOR_VIOLATION` | 409 Conflict |
| `ERR_CREDENTIAL_REQUIRED` | 409 Conflict |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_ROOMMATE_INCOMPATIBLE` | 409 Conflict |
| `ERR_MANIFEST_FULL` | 409 Conflict |
| `ERR_CARGO_OVERWEIGHT` | 409 Conflict |
| `ERR_CUTOFF_PASSED` | 409 Conflict |
| `ERR_CONTRACT_EXECUTION_WINDOW` | 409 Conflict |
| `ERR_MEMBER_NOT_IN` | 409 Conflict |
| `ERR_LEG_NOT_CHARTER` | 409 Conflict |
| `ERR_BUDGET_EXCEEDED` | 402 Payment Required |
| `ERR_INVALID_PER_DIEM_INPUT` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |

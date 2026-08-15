# Gleaning Farm Surplus Recovery API — Product Requirements Document

## 1. Introduction

Gleaning programs sit at the intersection of farm economics, volunteer logistics, and hunger relief: a grower with unharvested surplus needs a crew in the field inside a short harvest window, the produce must move under refrigeration rules to agencies with finite weekly capacity, and every pound must be accounted for twice — once as tax-deduction documentation for the donor and once as impact evidence for the grant funders who underwrite the program. This document defines the API for a gleaning and farm surplus recovery program that coordinates that entire chain, from the moment a donor farm publishes a surplus offer to the moment a county-level grant report is accepted.

The system's discriminating concerns are accountability and constraint enforcement. Witnessed liability waivers gate crew participation; weighed harvest lots must be verified by someone other than the person who weighed them; cold-chain temperature readings can disqualify a delivery outright; and allocations to recipient agencies are bounded simultaneously by what the field produced, what the truck can carry, and what the agency can absorb in a week. All program resources are mounted under the `/glean` prefix. Poundage, valuation, and impact calculations are deterministic and auditable, and the sections below specify them completely — global contracts first, then the business workflows, the endpoint catalogue, and the error catalogue.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request is authenticated through HTTP headers. Each request must carry an `X-User-Role` header naming one of the five declared roles — `ProgramCoordinator`, `CrewLeader`, `Volunteer`, `FoodSafetyOfficer`, or `GrantReviewer` — and, whenever the role is entity-backed, an `X-User-ID` header identifying the acting person. Requests with missing or malformed headers are rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Access to each operation is restricted by role per the endpoint catalogue in §4; an authenticated caller whose role is not permitted for the endpoint — including a `Volunteer` acting on another volunteer's assignment, or a `CrewLeader` who is not the event's designated leader — is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `CrewLeader`, `X-User-ID` is the `id` of the acting `Volunteer` — a crew leader is simply a certified volunteer — and ownership checks on any resource that references a `Volunteer` (for example, an event's `crew_leader_volunteer_id`) compare that foreign-key field to `X-User-ID`. The same holds when `X-User-Role` is `Volunteer`: `X-User-ID` is the `id` of the acting `Volunteer`, and an assignment's `volunteer_id` must match it on the confirm, decline, and hours-reporting actions. When `X-User-Role` is `ProgramCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`, and where a workflow needs a concrete person — such as the coordinator verifying a harvest lot — that identifier arrives explicitly in the request body. The same opaque treatment applies when `X-User-Role` is `FoodSafetyOfficer` and when it is `GrantReviewer`: an operator identifier with no entity backing and no ownership comparisons.

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

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter specifies the maximum number of items to return; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their `created_at` timestamp in ascending order.

List responses carry the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`. Many list endpoints additionally accept resource-specific filters — for example `county_code` on the farm and agency lists, or `status` on the offer, event, distribution, and report lists; each filter is named in the workflow section where the resource is introduced.

### 2.4. Common Resource Properties

All primary resources — farms, offers, volunteers, agencies, glean events, crew assignments, harvest lots, distributions, containers, vehicles, food-safety incidents, and grant reports — share four system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording the last modification; it refreshes on every mutation.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource, including mutations caused by cascading side effects from operations on other resources.

Three record types are immutable once written and therefore carry only `id` and `created_at` — both `updated_at` and `version` are absent from them: the **Waiver**, the **TempLog**, and the **DonationReceipt**.

### 2.5. The Logical Clock

The program's sense of time is a logical clock, never the wall clock. At server startup the current instant is exactly 2026-08-01T00:00:00Z. A `ProgramCoordinator`-only test-driving capability sets the clock to a supplied `to_iso8601` instant, and setting the clock causes the system to re-evaluate offer expiry: any offer still `OFFERED` whose `window_end` has been reached by the new instant transitions to `EXPIRED`, provided no glean event exists for that offer.

Beyond expiry, the logical clock drives the event start gate described in §3.3 and the ISO-8601 week assignment that decides which week a delivery counts against for agency capacity. Server-side timestamps such as a waiver's `signed_at` and a receipt's `issued_at` are also taken from the logical clock.

### 2.6. Validation Order and Terminal-State Lockdown

Every request is evaluated against a fixed, ordered sequence of gates, and the first gate that fails determines the error returned — later gates are never consulted on a failed request. The sequence is:

1. **Authentication** — the headers required by §2.1 must be present and well-formed, failing with `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Authorization** — the role must be permitted to invoke the endpoint, failing with `ERR_UNAUTHORIZED` (HTTP 403).
3. **Existence** — every identifier in the path (validated left to right) and every foreign key in the body must reference an existing resource, failing with `ERR_NOT_FOUND` (HTTP 404).
4. **State compatibility** — the target resource must be in a state that permits the requested transition, failing with `ERR_INVALID_STATE` (HTTP 409).
5. **Cold-chain delivery gate** — `ERR_COLD_CHAIN_BREACH` (§3.4, §3.5).
6. **Segregation of duties** — `ERR_SEGREGATION_OF_DUTIES` (§3.2, §3.3).
7. **Event window containment** — `ERR_EVENT_WINDOW_OUTSIDE_OFFER` (§3.3).
8. **Offer window overlap** — `ERR_OFFER_WINDOW_OVERLAP` (§3.1).
9. **Volunteer double-booking** — `ERR_VOLUNTEER_DOUBLE_BOOKED` (§3.2).
10. **Vehicle schedule conflict** — `ERR_VEHICLE_SCHEDULE_CONFLICT` (§3.3).
11. **Waiver presence** — `ERR_WAIVER_MISSING` (§3.2).
12. **Crew capacity** — `ERR_CREW_FULL` (§3.2).
13. **Refrigeration matching** — `ERR_VEHICLE_REFRIGERATION_MISMATCH` (§3.3, §3.5).
14. **Allocation feasibility** — `ERR_ALLOCATION_EXCEEDS_HARVEST` (§3.5).
15. **Cull sanity** — `ERR_CULL_EXCEEDS_NET` (§3.3).
16. **Vehicle payload** — `ERR_VEHICLE_PAYLOAD_EXCEEDED` (§3.3).
17. **Agency weekly capacity** — `ERR_AGENCY_CAPACITY_EXCEEDED` (§3.5).
18. **Uniqueness** — `ERR_DUPLICATE` (§3.1, §3.2, §3.3, §3.6).
19. **Optimistic-concurrency staleness** — `ERR_STALE_EVENT_VERSION` or `ERR_STALE_OFFER_VERSION` (§2.9).
20. **Terminal-state lockdown** — any action invoked on a resource that has already reached a terminal state is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409).
21. **Event start timing** — `ERR_EVENT_NOT_STARTED` (§3.3).
22. **Volunteer standing** — `ERR_VOLUNTEER_SUSPENDED` (§3.2).
23. **Farm active gate** — `ERR_FARM_INACTIVE` (§3.1).
24. **Agency active gate** — `ERR_AGENCY_INACTIVE` (§3.5).
25. **Open-incident gate** — `ERR_INCIDENT_OPEN` (§3.4, §3.6).
26. **Request shape** — required fields present and typed per the resource model, enum values within their declared sets, failing with `ERR_INVALID_REQUEST` (HTTP 400).

Two consequences of this ordering are worth internalizing. A confirmation request that would violate both the waiver gate and the crew-capacity gate is rejected with `ERR_WAIVER_MISSING`, because the waiver check runs first; likewise a distribution create carrying a stale event version and an over-capacity plan is rejected with `ERR_AGENCY_CAPACITY_EXCEEDED`, because the capacity check runs before the concurrency check. And a request with a malformed body against a non-existent resource surfaces `ERR_NOT_FOUND`, since existence precedes shape.

### 2.7. Nested Identifier Resolution

Identifiers are resolved strictly left to right. When an endpoint path contains multiple `{id}` segments, the server validates each segment's existence in sequence and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not correspond to an existing resource, without consulting later segments or the request body. Foreign keys carried in a request body are checked for existence under the same gate, before any business rule runs.

### 2.8. Poundage, Valuation, and Rounding Precision

Weights are carried at one decimal place with round-half-up rounding; the inputs to a lot's net-weight arithmetic are rounded to one decimal place before subtraction, and the subtraction itself is exact. Salvage ratios are computed to four decimal places, round half up. Donation valuations are expressed in integer cents, rounded half up. Meal equivalents are truncated down to a whole number — never rounded. Temperature comparisons are made at one decimal place and are strict: a reading must be above the threshold to count as a breach; a reading exactly at the threshold does not.

### 2.9. Optimistic Concurrency Control

Exactly two write operations take a concurrency field; no other endpoint accepts a version field.

Creating a distribution requires the request to carry `expected_event_version`, holding the client's last observed `version` of the parent glean event. If the event's current `version` has advanced since that observation — for instance because another writer has just created or cancelled a distribution on the same event, advancing the event's version — the create is rejected with `ERR_STALE_EVENT_VERSION` (HTTP 412), so the client cannot allocate against a view of remaining undistributed pounds it has not observed.

Closing an offer requires `expected_offer_version`, holding the client's last observed `version` of the offer. If the offer's current `version` has advanced since that observation — for example because a late lot verification or an incident resolution has moved it forward — the close is rejected with `ERR_STALE_OFFER_VERSION` (HTTP 412), because the receipt-poundage basis the client relied upon is no longer current.

### 2.10. Cascades and Cross-Entity Consistency

State changes propagate across entity boundaries in both directions. When a parent resource undergoes a transition that renders its children moot — cancelling an offer, cancelling an event — the system resolves every dependent child in the same breath: events are cancelled, pending and confirmed assignments are declined, containers and vehicles are released. When children change in ways that bear on the parent's state — the last event of an offer finishing, a distribution landing against an agency — the parent's derived totals and lifecycle position are recomputed immediately, without requiring an explicit client request on the parent.

Each such reconciliation independently mutates the affected resource: every mutation, including one caused by a cascade, refreshes `updated_at` and increments `version`. System-initiated transitions — offer expiry, the crew-full flip, the suspension of a volunteer — fire automatically the moment their criteria are satisfied.

## 3. Business Logic & Workflows

### 3.1. Donor Farms and Surplus Offers

A `ProgramCoordinator` registers each donor farm with its legal `farm_name`, the `contact_email` used as the primary channel for donor tax documentation, the `county_code` that later anchors grant-reporting rollups, and the `donor_tin` printed on donation receipts. The farm's `active_flag` defaults to true at registration; a farm whose flag has been cleared may not publish new surplus offers — such an attempt is rejected with `ERR_FARM_INACTIVE`. Over time the farm's `lifetime_donated_lbs` accumulates the credited pounds of every closed glean event sourced from the farm. Farms can be listed with an optional `county_code` filter or fetched individually.

Against an active farm, the coordinator publishes a **SurplusOffer** carrying the `farm_id`, a `crop_code` (values such as `SWEET_CORN` or `APPLES`), the farmer's `estimated_lbs` — which must be greater than zero — and the harvest window: `window_start` is inclusive, `window_end` is exclusive, and the end must fall strictly after the start. The offer also declares a `perishability_class` — `HIGH` for leafy greens and berries with a 24-hour cold-chain limit, `MEDIUM` for stone fruit with a 72-hour limit, or `LOW` for roots and winter squash with a 168-hour limit — and a `requires_refrigeration` flag indicating whether cold chain is mandatory from field to agency. A new offer is born `OFFERED`.

One overlap restriction protects the donor calendar: a farm may not hold two non-terminal offers for the same `crop_code` whose half-open harvest windows overlap, although adjacency — one window ending exactly when the other begins — is permitted. A violating publish is rejected with `ERR_OFFER_WINDOW_OVERLAP`. Publishing an offer touches only the offer; the farm's own `version` is not advanced.

From `OFFERED`, an offer's life proceeds through `SCHEDULED` and `GLEANED` to `CLOSED`, with `CANCELLED` and `EXPIRED` as the other terminal outcomes. Expiry is clock-driven: when the logical clock reaches an offer's `window_end` while the offer is still `OFFERED` and no glean event exists for it, the system moves the offer to `EXPIRED` and bumps its `version`. Cancellation has two shapes. Cancelling an offer still `OFFERED` is permitted only while no glean event of the offer has reached `FULL`, `IN_PROGRESS`, `HARVESTED`, or `RECONCILED`; any events sitting in `DRAFT` or `OPEN` are cascade-cancelled, and their crew assignments in `PENDING` or `CONFIRMED` become `DECLINED`. Cancelling a `SCHEDULED` offer is permitted only while every event of the offer is in `DRAFT`, `OPEN`, or `CANCELLED`; the same cascade then runs — draft and open events are cancelled, their pending and confirmed assignments are declined — and additionally every container held by those events returns to `AVAILABLE` and every assigned vehicle returns to `AVAILABLE`. Either cancellation bumps the offer's `version`. Offers can be listed with optional `farm_id` and `status` filters.

### 3.2. Volunteers, Waivers, and Crew Assignments

Volunteers are registered by a coordinator with a `full_name` and an `email` that must be unique across all volunteers — a duplicate address is rejected with `ERR_DUPLICATE`. Registration optionally sets `crew_leader_certified`, which defaults to false; only a certified volunteer may be named as an event's crew leader. A volunteer is born `ACTIVE`, and the computed `no_show_count` tracks how many of their assignments have ended `NO_SHOW`: when that count reaches two, the system moves the volunteer to `SUSPENDED`. A coordinator can later reinstate a suspended volunteer, returning them to `ACTIVE` and resetting `no_show_count` to zero. The volunteer list supports an optional `email` filter.

Before setting foot in the field, a volunteer signs a liability **Waiver** scoped to a single event. The signing payload carries the `volunteer_id` of the signer, the `glean_event_id`, an opaque `signature_payload` attestation string, and a `witness_volunteer_id` naming the crew leader who witnessed the signature. Segregation of duties applies at signing: the witness must differ from the signer, and a waiver naming the same volunteer in both roles is rejected with `ERR_SEGREGATION_OF_DUTIES`. The server stamps `signed_at` from the logical clock, and because a waiver is immutable once recorded it carries no `updated_at` or `version` (§2.4). Waivers can be fetched individually, listed per volunteer through the volunteer's waiver listing, or listed per event.

A coordinator or a crew leader then builds the crew by inviting volunteers: each **CrewAssignment** is created from a `glean_event_id` and a `volunteer_id` and starts in `PENDING`. Only the invited volunteer may answer — confirming or declining another volunteer's assignment is rejected with `ERR_UNAUTHORIZED`.

Confirming an assignment runs a fixed gate order. The event must be in `OPEN` or `FULL`, since crews cannot join an event already running or finished (`ERR_INVALID_STATE`). Next, double-booking: the volunteer may not hold `CONFIRMED` assignments on two events whose half-open schedule intervals — each running from its `scheduled_start` up to but not including its `scheduled_end` — overlap, with adjacency again permitted; a conflict is rejected with `ERR_VOLUNTEER_DOUBLE_BOOKED`. Next, waiver presence: a waiver must exist pairing this volunteer with this event and witnessed by a different volunteer, failing with `ERR_WAIVER_MISSING`. Next, capacity: confirming must not push the event's `crew_confirmed_count` above its `crew_capacity`, failing with `ERR_CREW_FULL`. Last, standing: a `SUSPENDED` volunteer cannot confirm and is rejected with `ERR_VOLUNTEER_SUSPENDED`. On success the assignment becomes `CONFIRMED`, the server stamps `confirmed_at` from the logical clock, and the event's `crew_confirmed_count` rises by one — when the count reaches `crew_capacity`, an `OPEN` event flips to `FULL`, while a count one short of capacity leaves it `OPEN`.

Declining is lighter. A `PENDING` assignment may be declined by its volunteer without further preconditions, moving it to `DECLINED`. A `CONFIRMED` assignment may be declined only while its event is still `OPEN` or `FULL`; doing so drops the event's `crew_confirmed_count` by one, and if the event was `FULL` it reopens to `OPEN`.

Once the crew is in the field, hours reporting is a distinct volunteer action: while the event is `IN_PROGRESS`, the volunteer records `hours_worked` on their own `CONFIRMED` assignment. The assignment remains `CONFIRMED` at that point — recorded hours are required for the assignment's later arrival at `COMPLETED`, which the finish sweep described in §3.3 performs.

### 3.3. Planning and Running a Glean Event

A **GleanEvent** is created by a coordinator against an offer, with a payload of `surplus_offer_id`, `scheduled_start`, `scheduled_end`, `crew_leader_volunteer_id`, `assigned_vehicle_id`, and `crew_capacity`. The named crew leader must be a volunteer whose `crew_leader_certified` is true, and `crew_capacity` must be greater than zero. The first event created against an `OFFERED` offer moves the offer to `SCHEDULED` and bumps the offer's `version`; that first creation also requires the farm's `active_flag` still set and the logical clock's current instant to fall before the offer's `window_end`. Further events may be created while the offer is `SCHEDULED` without changing the offer's status — one offer may host many events — but creating an event against an offer in `GLEANED`, `CLOSED`, `CANCELLED`, or `EXPIRED` is rejected with `ERR_INVALID_STATE`. A new event starts in `DRAFT`.

Creation-time checks run in the global order of §2.6. Window containment: `scheduled_start` must fall on or after the offer's `window_start`, `scheduled_end` must fall on or before the offer's `window_end`, and the start must be strictly before the end — otherwise `ERR_EVENT_WINDOW_OUTSIDE_OFFER`. Vehicle scheduling: the assigned vehicle may not already sit on another event in `OPEN`, `FULL`, `IN_PROGRESS`, or `HARVESTED` whose half-open schedule interval overlaps this one — adjacency permitted — on pain of `ERR_VEHICLE_SCHEDULE_CONFLICT`. Refrigeration matching: the offer's `requires_refrigeration` flag must equal the vehicle's `refrigerated` flag, otherwise `ERR_VEHICLE_REFRIGERATION_MISMATCH`.

Two logistics registries support events. A **Container** is registered with a human-readable `label` that must be unique (`ERR_DUPLICATE`), a `tare_lbs` empty weight greater than zero, a `capacity_lbs` maximum net payload greater than zero, and a `refrigerated` flag marking cold-chain totes; containers move among `AVAILABLE`, `IN_USE`, and `RETIRED`. A **Vehicle** is registered with a unique `plate` (`ERR_DUPLICATE`), a `payload_capacity_lbs` greater than zero, and a `refrigerated` flag; vehicles move among `AVAILABLE`, `ASSIGNED`, and `OUT_OF_SERVICE`.

Publishing moves an event `DRAFT` → `OPEN`. The offer must be `SCHEDULED`, the assigned vehicle must currently be `AVAILABLE`, and the event's schedule must still sit inside the offer's harvest window; the vehicle schedule-conflict check runs again at publish. Publishing transitions the vehicle from `AVAILABLE` to `ASSIGNED` and bumps the event's `version`.

Starting the work is the crew leader's call, and only the designated one: the acting crew leader must be the volunteer referenced by the event's `crew_leader_volunteer_id`, anyone else drawing `ERR_UNAUTHORIZED`. Starting moves `OPEN` → `IN_PROGRESS` or `FULL` → `IN_PROGRESS`. The logical clock must have reached `scheduled_start` and must not yet have reached `scheduled_end`, otherwise the start is rejected with `ERR_EVENT_NOT_STARTED`. Starting from `OPEN` additionally requires at least one confirmed crew member; starting from `FULL` needs no such check, since the crew is by definition at capacity.

While the event is `IN_PROGRESS`, the crew leader records each **HarvestLot** as it is weighed: `glean_event_id`, `container_id`, the field-scale `gross_lbs` (greater than zero), an optional `tare_lbs` that defaults to the referenced container's own `tare_lbs` when omitted, `cull_lbs` for field-culled non-food pounds (at least zero, and never more than the gross weight minus the tare weight — an excess is rejected with `ERR_CULL_EXCEEDS_NET`), and `recorded_by_volunteer_id` naming the crew leader who weighed the lot. The system computes `net_lbs` as the gross weight minus the tare weight minus the cull weight, with inputs rounded per §2.8. The referenced container must be `AVAILABLE` or already `IN_USE` by this event. A lot is born `PENDING`.

Verification is a coordinator's act and a second pair of eyes: verifying a `PENDING` lot supplies `verified_by_coordinator_id`, which must differ from the lot's `recorded_by_volunteer_id` (`ERR_SEGREGATION_OF_DUTIES`), and requires the event still `IN_PROGRESS`. Verification also runs the payload check — the sum of `net_lbs` across the event's `VERIFIED` lots, including the one being verified, may not exceed the assigned vehicle's `payload_capacity_lbs`, although a total exactly equal to the capacity is allowed; an excess is rejected with `ERR_VEHICLE_PAYLOAD_EXCEEDED`. A successful verification moves the lot to `VERIFIED`, transitions the referenced container from `AVAILABLE` to `IN_USE`, and recomputes the event's `total_harvested_lbs` as the sum of `net_lbs` over its `VERIFIED` lots only — `PENDING` and `REJECTED` lots never count. A coordinator may instead reject a pending lot, moving it to `REJECTED`.

Finishing moves the event `IN_PROGRESS` → `HARVESTED` and requires at least one `VERIFIED` lot. The finish sweep resolves the whole roster: every `CONFIRMED` assignment becomes `COMPLETED`, and every assignment still `PENDING` becomes `NO_SHOW`, incrementing that volunteer's `no_show_count` and flipping the volunteer to `SUSPENDED` when the count reaches two. The event's `total_harvested_lbs` is recomputed, and the offer re-evaluates its `GLEANED` transition: when every event of a `SCHEDULED` offer has reached `HARVESTED` or `RECONCILED` and at least one reached `HARVESTED`, the system moves the offer to `GLEANED` and recomputes the offer's `actual_lbs` as the sum of each of its events' `total_harvested_lbs`.

Reconciliation is the coordinator's closing pass over a harvested event, moving `HARVESTED` → `RECONCILED`. It is permitted only when every distribution of the event has reached `DELIVERED`, `SHORTFALL`, or `CANCELLED`, every harvest lot has reached `VERIFIED` or `REJECTED`, and no food-safety incident of the event remains `OPEN` — an open incident blocks reconciliation with `ERR_INCIDENT_OPEN`. Reconciliation recomputes the event's `total_distributed_lbs` and `undistributed_lbs`, returns every container referenced by the event's `VERIFIED` lots from `IN_USE` to `AVAILABLE`, returns the vehicle from `ASSIGNED` to `AVAILABLE`, and re-evaluates the offer's `GLEANED` transition once more.

Cancellation tidies up early-stage events. A coordinator may cancel a `DRAFT` event outright, moving it to `CANCELLED`. Cancelling an `OPEN` event declines its `PENDING` and `CONFIRMED` assignments and returns the vehicle from `ASSIGNED` to `AVAILABLE`. Events can be listed with optional `surplus_offer_id`, `status`, `crew_leader_volunteer_id`, and `assigned_vehicle_id` filters.

### 3.4. Cold Chain and Food Safety

During and after harvest, the crew leader or a food-safety officer appends temperature readings: each **TempLog** carries the `glean_event_id`, the `recorded_at` instant of the reading, and the observed `temp_f`. The server computes `breach_flag` at write time. For produce whose `perishability_class` is `HIGH` or `MEDIUM`, a reading strictly above 41.0°F is a breach — a reading of exactly 41.0 is not; for `LOW`, the threshold is 55.0°F under the same strict-above rule. When a breaching log lands, every `SCHEDULED` distribution of that event has its `cold_chain_intact` recomputed to false, which in turn gates delivery for refrigeration-required offers. Temp logs are immutable records and can be listed with an optional `glean_event_id` filter.

Each distribution's `cold_chain_intact` begins true and becomes false exactly when a breaching temperature log attached to the distribution's event occurred between the event reaching `HARVESTED` and that distribution's delivery. For an offer marked `requires_refrigeration`, delivering a distribution requires `cold_chain_intact` still true; a breach surfaces at delivery time as `ERR_COLD_CHAIN_BREACH`.

When product is lost to a safety concern, the crew leader or food-safety officer opens a **FoodSafetyIncident** with the `glean_event_id`, a `severity` — `MINOR` for an isolated container loss or `CRITICAL` for a whole-load condemnation — the `condemned_lbs` (greater than zero), and `reported_by_volunteer_id`. An incident is born `OPEN`, and an `OPEN` incident blocks both event reconciliation and offer closing with `ERR_INCIDENT_OPEN`. Only a `FoodSafetyOfficer` may resolve an incident, supplying a `disposition`: `COMPOST` moves it to `RESOLVED_COMPOST`, `ANIMAL_FEED` to `RESOLVED_ANIMAL_FEED`, and `LANDFILL` to `RESOLVED_LANDFILL`. Each resolution recomputes the event's `undistributed_lbs` — the pounds remaining of `total_harvested_lbs` after subtracting `total_distributed_lbs` and the condemned pounds of the event's resolved incidents. Incidents can be listed with optional `glean_event_id` and `reported_by_volunteer_id` filters.

### 3.5. Distributing the Harvest to Agencies

Recipient agencies are registered by a coordinator with an `agency_name`, the `county_code` they serve (used for grant rollup matching), a `weekly_capacity_lbs` greater than zero — the most produce the agency can accept in one ISO week — a `refrigeration_capable` flag, and an `active_flag` that defaults to true. The computed `current_week_committed_lbs` tracks the pounds committed to the agency for the current ISO week, where "current" is the ISO-8601 week containing the logical clock's instant: it sums the `planned_lbs` of the agency's `SCHEDULED` distributions and the `delivered_lbs` of its `DELIVERED` and `SHORTFALL` distributions whose `delivery_date` falls in that week; `CANCELLED` distributions are excluded entirely. Agencies can be listed with an optional `county_code` filter.

Once an event has reached `HARVESTED`, a coordinator allocates pounds from it to an agency by creating a **Distribution** with `glean_event_id`, `agency_id`, `planned_lbs` (greater than zero), a `delivery_date` that fixes the ISO week used for capacity accounting, and `expected_event_version` (§2.9). A new distribution is born `SCHEDULED`, and creating one advances the event's `version` — the very reason the concurrency field exists: another writer's allocation or cancellation on the same event advances it too, so the pinned version guards the creator's view of what remains unallocated.

Creation enforces a fixed sequence of business gates after the generic state check. Refrigeration capability: an agency receiving a load from a refrigeration-required offer must be `refrigeration_capable`, failing with `ERR_VEHICLE_REFRIGERATION_MISMATCH`. Allocation feasibility: `planned_lbs` may not exceed the event's available pounds — computed as `total_harvested_lbs` minus the `planned_lbs` of the event's `SCHEDULED` distributions, minus the `delivered_lbs` of its `DELIVERED` and `SHORTFALL` distributions, minus the `condemned_lbs` of its resolved incidents — although a plan exactly equal to the available pounds is allowed and fully allocates the event; an excess is rejected with `ERR_ALLOCATION_EXCEEDS_HARVEST`. Agency weekly capacity: the agency's committed pounds for the delivery's ISO week plus the new `planned_lbs` may not exceed `weekly_capacity_lbs`, with a total exactly equal to the capacity allowed; an excess is rejected with `ERR_AGENCY_CAPACITY_EXCEEDED`. Optimistic concurrency: `expected_event_version` must match the event's current `version`, failing with `ERR_STALE_EVENT_VERSION`. Agency standing: a distribution created against an agency whose `active_flag` is false is rejected with `ERR_AGENCY_INACTIVE`. A successful creation also recomputes the agency's `current_week_committed_lbs` and the event's `total_distributed_lbs`.

Delivery is recorded by a crew leader supplying `delivered_lbs`, the actual delivered pounds. When the delivered amount equals `planned_lbs`, the distribution moves `SCHEDULED` → `DELIVERED`; when it is greater than zero but less than planned, the distribution moves `SCHEDULED` → `SHORTFALL`, and the agency's committed total then counts the delivered pounds rather than the planned pounds. Both outcomes require the event to be `HARVESTED` and — for refrigeration-required offers — `cold_chain_intact` still true, failing with `ERR_COLD_CHAIN_BREACH` otherwise. Either outcome recomputes the agency's committed pounds and the event's totals. A coordinator may also cancel a `SCHEDULED` distribution, moving it to `CANCELLED` and recomputing the agency's committed pounds. Distributions can be listed with optional `glean_event_id`, `agency_id`, and `status` filters, and an agency's inbound flow can be reviewed through the agency's distribution listing.

### 3.6. Closing an Offer: Salvage Ratio, Receipts, and Donor Credit

When every glean event of a `GLEANED` offer has reached `RECONCILED` or `CANCELLED` and no food-safety incident on any of those events remains `OPEN` (`ERR_INCIDENT_OPEN`), the coordinator closes the offer. The close request must carry `expected_offer_version` matching the offer's current `version`; a mismatch — say a late lot verification or incident resolution advanced the offer since the client last read it — is rejected with `ERR_STALE_OFFER_VERSION`, per §2.9. Closing moves the offer to `CLOSED` and bumps its `version`.

Closing performs the offer's final accounting. The `salvage_ratio` is computed as `actual_lbs` divided by `estimated_lbs`, rounded half-up to four decimal places; the raw ratio always uses all verified pounds, including any later condemned. Alongside it, grant reporting draws on a net-of-condemnation variant — `actual_lbs` minus the resolved incidents' condemned pounds, divided by `estimated_lbs`, likewise at four decimal places round half up.

Closing also mints the donor's **DonationReceipt** — exactly one per offer, and a second issuance for the same offer is rejected with `ERR_DUPLICATE`. The receipt copies `surplus_offer_id` and `farm_id` from the offer at issuance and stamps `issued_at` from the logical clock; as an immutable record it carries no `updated_at` or `version`. The credited pounds follow two variants. When no food-safety incident on any of the offer's events ever reached a resolved state, `receipt_lbs` equals `actual_lbs` — the gross basis. When at least one incident has resolved, `receipt_lbs` is `actual_lbs` minus the total `condemned_lbs` of the resolved incidents across the offer's events, floored at zero. The receipt's `fair_market_value_cents` is the receipt pounds multiplied by the per-pound price keyed on the offer's `crop_code` — 33 cents for `SWEET_CORN`, 41 for `APPLES`, 74 for `LEAFY_GREENS`, 58 for `TOMATOES`, 29 for `ROOT_VEG`, and 36 for `WINTER_SQUASH`, with any other crop valued at a default of 40 cents per pound — rounded half-up to a whole cent.

The credited pounds then roll into the farm's `lifetime_donated_lbs`, bumping the farm's `version` as part of the same close. Afterward, the receipt for a closed offer can be fetched directly — a list of zero or one entries — and all receipts issued to a farm can be listed through the farm's receipt listing, just as the farm's offers can be listed through its offer listing.

### 3.7. Grant Reporting and Impact Metrics

A coordinator opens a **GrantReport** for a county by supplying `county_code`, a `period_start` that inclusively begins the reporting period, and a `period_end` that exclusively ends it and must fall strictly after the start. A report is born `DRAFT`. Submitting moves it `DRAFT` → `SUBMITTED`; a `GrantReviewer` then accepts it (`SUBMITTED` → `ACCEPTED`, terminal) or returns it (`SUBMITTED` → `RETURNED`), and a returned report may be resubmitted, moving `RETURNED` → `SUBMITTED`.

Submission freezes the numbers. Both the initial submission and any resubmission recompute the report's three metrics at that instant, and the frozen snapshot never changes afterward, no matter what later happens to farms, agencies, lots, or incidents. The scope is the set of glean events whose offer's farm `county_code` equals the report's county, whose offer has reached `CLOSED`, and whose offer's close timestamp — its `updated_at` at the moment of the `CLOSED` transition — falls within the half-open period from `period_start` inclusive to `period_end` exclusive. Within that scope, `total_gleaned_lbs` is the sum of the events' `total_harvested_lbs` minus the `condemned_lbs` of their resolved incidents, expressed at one decimal place round half up. The `meals_equivalent` multiplies that total by 1.2 meals per pound and truncates the product down to a whole number. The `agency_count` counts the distinct agencies that received `DELIVERED` distributions from the in-scope events. Reports can be listed with optional `county_code` and `status` filters.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources — a farm, offer, volunteer, waiver, agency, container, vehicle, event, assignment, lot, distribution, temperature log, incident, or grant report — return a `201 Created` status code. Operations that modify an existing resource — every state-transition action such as publish, start, finish, reconcile, confirm, decline, verify, deliver, close, resolve, submit, accept, return, reinstate, and the clock-setting capability — return a `200 OK` status code. Request payloads, derived fields, and side effects are specified in the workflow narratives of §3; this table is a summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/glean/farms` | Register a donor farm | ProgramCoordinator |
| GET | `/glean/farms` | List farms; optional `county_code` filter | ProgramCoordinator, GrantReviewer, FoodSafetyOfficer |
| GET | `/glean/farms/{id}` | Fetch one farm | ProgramCoordinator, GrantReviewer |
| POST | `/glean/offers` | Publish a surplus offer (born `OFFERED`); enforces per-farm per-crop window non-overlap | ProgramCoordinator |
| GET | `/glean/offers` | List offers; optional `farm_id` and `status` filters | ProgramCoordinator, GrantReviewer, FoodSafetyOfficer, CrewLeader |
| GET | `/glean/offers/{id}` | Fetch one offer | ProgramCoordinator, GrantReviewer, FoodSafetyOfficer, CrewLeader |
| POST | `/glean/offers/{id}/cancel` | Cancel an offer in `OFFERED` or `SCHEDULED`; cascades to events, assignments, containers, vehicles | ProgramCoordinator |
| POST | `/glean/offers/{id}/close` | Close a `GLEANED` offer; computes salvage ratio, mints the donation receipt, credits the farm; OCC-guarded | ProgramCoordinator |
| GET | `/glean/offers/{id}/receipt` | Fetch the donation receipt minted at close (array of zero or one) | ProgramCoordinator, GrantReviewer |
| GET | `/glean/farms/{id}/receipts` | List donation receipts issued to a farm | ProgramCoordinator, GrantReviewer |
| GET | `/glean/farms/{id}/offers` | List offers of a farm | ProgramCoordinator, GrantReviewer |
| POST | `/glean/volunteers` | Register a volunteer | ProgramCoordinator |
| GET | `/glean/volunteers` | List volunteers; optional `email` filter | ProgramCoordinator |
| GET | `/glean/volunteers/{id}` | Fetch one volunteer | ProgramCoordinator |
| POST | `/glean/volunteers/{id}/reinstate` | Reinstate a `SUSPENDED` volunteer to `ACTIVE`; resets the no-show count | ProgramCoordinator |
| GET | `/glean/volunteers/{id}/waivers` | List waivers signed by a volunteer | ProgramCoordinator |
| POST | `/glean/waivers` | Sign a liability waiver for an event; witness must differ from signer | Volunteer |
| GET | `/glean/waivers/{id}` | Fetch one waiver | ProgramCoordinator |
| GET | `/glean/events/{id}/waivers` | List waivers for an event | ProgramCoordinator, CrewLeader |
| POST | `/glean/agencies` | Register a recipient agency | ProgramCoordinator |
| GET | `/glean/agencies` | List agencies; optional `county_code` filter | ProgramCoordinator, GrantReviewer |
| GET | `/glean/agencies/{id}` | Fetch one agency | ProgramCoordinator, GrantReviewer |
| GET | `/glean/agencies/{id}/distributions` | List distributions for an agency | ProgramCoordinator, GrantReviewer |
| POST | `/glean/containers` | Register a container | ProgramCoordinator |
| GET | `/glean/containers` | List containers | ProgramCoordinator, CrewLeader |
| GET | `/glean/containers/{id}` | Fetch one container | ProgramCoordinator, CrewLeader |
| POST | `/glean/vehicles` | Register a vehicle | ProgramCoordinator |
| GET | `/glean/vehicles` | List vehicles | ProgramCoordinator, CrewLeader |
| GET | `/glean/vehicles/{id}` | Fetch one vehicle | ProgramCoordinator, CrewLeader |
| POST | `/glean/events` | Create a glean event against an offer (first event moves it to `SCHEDULED`) | ProgramCoordinator |
| GET | `/glean/events` | List events; optional `surplus_offer_id`, `status`, `crew_leader_volunteer_id`, `assigned_vehicle_id` filters | ProgramCoordinator, CrewLeader, FoodSafetyOfficer, GrantReviewer |
| GET | `/glean/events/{id}` | Fetch one event | ProgramCoordinator, CrewLeader, FoodSafetyOfficer, GrantReviewer |
| POST | `/glean/events/{id}/publish` | Publish a `DRAFT` event to `OPEN`; assigns the vehicle | ProgramCoordinator |
| POST | `/glean/events/{id}/cancel` | Cancel a `DRAFT` or `OPEN` event; declines assignments; releases the vehicle | ProgramCoordinator |
| POST | `/glean/events/{id}/start` | Start an `OPEN` or `FULL` event; only the designated crew leader; time-gated | CrewLeader |
| POST | `/glean/events/{id}/finish` | Finish an `IN_PROGRESS` event; sweeps assignment outcomes | CrewLeader |
| POST | `/glean/events/{id}/reconcile` | Reconcile a `HARVESTED` event; releases containers and vehicle | ProgramCoordinator |
| POST | `/glean/assignments` | Invite a volunteer to an event (creates a `PENDING` assignment) | ProgramCoordinator, CrewLeader |
| GET | `/glean/assignments` | List assignments; optional `glean_event_id` and `volunteer_id` filters | ProgramCoordinator, CrewLeader |
| GET | `/glean/assignments/{id}` | Fetch one assignment | ProgramCoordinator, CrewLeader |
| POST | `/glean/assignments/{id}/confirm` | Confirm a `PENDING` assignment; requires waiver, standing, capacity headroom, no double-booking | Volunteer |
| POST | `/glean/assignments/{id}/decline` | Decline a `PENDING` or `CONFIRMED` assignment; may reopen a `FULL` event | Volunteer |
| POST | `/glean/assignments/{id}/complete` | Record `hours_worked` on a `CONFIRMED` assignment of an `IN_PROGRESS` event | Volunteer |
| POST | `/glean/lots` | Record a harvest lot in `PENDING`; validates cull against gross minus tare | CrewLeader |
| GET | `/glean/lots` | List lots; optional `glean_event_id`, `container_id`, `recorded_by_volunteer_id`, `verified_by_coordinator_id` filters | ProgramCoordinator, CrewLeader, FoodSafetyOfficer |
| GET | `/glean/lots/{id}` | Fetch one lot | ProgramCoordinator, CrewLeader, FoodSafetyOfficer |
| POST | `/glean/lots/{id}/verify` | Verify a `PENDING` lot; segregation of duties; vehicle payload check | ProgramCoordinator |
| POST | `/glean/lots/{id}/reject` | Reject a `PENDING` lot | ProgramCoordinator |
| POST | `/glean/distributions` | Allocate pounds from a `HARVESTED` event to an agency; OCC on the event version | ProgramCoordinator |
| GET | `/glean/distributions` | List distributions; optional `glean_event_id`, `agency_id`, `status` filters | ProgramCoordinator, GrantReviewer, CrewLeader |
| GET | `/glean/distributions/{id}` | Fetch one distribution | ProgramCoordinator, GrantReviewer, CrewLeader |
| POST | `/glean/distributions/{id}/deliver` | Record a delivery: `DELIVERED` at plan, `SHORTFALL` below plan; cold-chain gate | CrewLeader |
| POST | `/glean/distributions/{id}/cancel` | Cancel a `SCHEDULED` distribution | ProgramCoordinator |
| POST | `/glean/templogs` | Append a temperature reading; computes the breach flag | CrewLeader, FoodSafetyOfficer |
| GET | `/glean/templogs` | List temperature logs; optional `glean_event_id` filter | ProgramCoordinator, FoodSafetyOfficer |
| GET | `/glean/templogs/{id}` | Fetch one temperature log | ProgramCoordinator, FoodSafetyOfficer |
| POST | `/glean/incidents` | Open a food-safety incident against an event | CrewLeader, FoodSafetyOfficer |
| GET | `/glean/incidents` | List incidents; optional `glean_event_id` and `reported_by_volunteer_id` filters | ProgramCoordinator, FoodSafetyOfficer, GrantReviewer |
| GET | `/glean/incidents/{id}` | Fetch one incident | ProgramCoordinator, FoodSafetyOfficer, GrantReviewer |
| POST | `/glean/incidents/{id}/resolve` | Resolve an incident with a `disposition` | FoodSafetyOfficer |
| POST | `/glean/reports` | Create a grant report in `DRAFT` for a county and period | ProgramCoordinator |
| GET | `/glean/reports` | List grant reports; optional `county_code` and `status` filters | ProgramCoordinator, GrantReviewer |
| GET | `/glean/reports/{id}` | Fetch one report | ProgramCoordinator, GrantReviewer |
| POST | `/glean/reports/{id}/submit` | Submit (or resubmit) a report; snapshots the impact metrics | ProgramCoordinator |
| POST | `/glean/reports/{id}/accept` | Accept a `SUBMITTED` report | GrantReviewer |
| POST | `/glean/reports/{id}/return` | Return a `SUBMITTED` report | GrantReviewer |
| POST | `/_clock/set_current_utc` | Test-driving capability: set the logical clock | ProgramCoordinator |

## 5. Error Code Catalogue

Trigger conditions for each error live in the workflow narratives of §2 and §3; this table is a summary only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_DUPLICATE` | 409 |
| `ERR_STALE_EVENT_VERSION` | 412 |
| `ERR_STALE_OFFER_VERSION` | 412 |
| `ERR_COLD_CHAIN_BREACH` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 422 |
| `ERR_EVENT_WINDOW_OUTSIDE_OFFER` | 422 |
| `ERR_OFFER_WINDOW_OVERLAP` | 422 |
| `ERR_VOLUNTEER_DOUBLE_BOOKED` | 422 |
| `ERR_VEHICLE_SCHEDULE_CONFLICT` | 422 |
| `ERR_WAIVER_MISSING` | 422 |
| `ERR_CREW_FULL` | 422 |
| `ERR_VEHICLE_REFRIGERATION_MISMATCH` | 422 |
| `ERR_ALLOCATION_EXCEEDS_HARVEST` | 422 |
| `ERR_CULL_EXCEEDS_NET` | 422 |
| `ERR_VEHICLE_PAYLOAD_EXCEEDED` | 422 |
| `ERR_AGENCY_CAPACITY_EXCEEDED` | 422 |
| `ERR_VOLUNTEER_SUSPENDED` | 422 |
| `ERR_FARM_INACTIVE` | 422 |
| `ERR_AGENCY_INACTIVE` | 422 |
| `ERR_INCIDENT_OPEN` | 422 |
| `ERR_EVENT_NOT_STARTED` | 422 |

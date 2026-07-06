# Snow Tubing Winter Park API — Product Requirements Document

## 1. Introduction

Winter-park snow-tubing operations live or die on two things that fight each other: keeping every lane as full as the weather safely allows, and never letting a rider onto a closed or oversubscribed hill. This API is the booking and operations backbone for a snow-tubing resort that sells timed session tickets, rents tubes and safety gear, hosts group parties, redeems season passes, and continuously re-grades the whole park against live snow and wind readings.

The system models a single winter park as a hierarchical root under which lanes, time blocks, and weather readings live, while session tickets, group reservations, season passes, equipment rentals, add-ons, and conveyor turns are wired in by reference. The defining tension is **posture-driven gating**: the park's operational posture is a derived aggregate over the latest weather reading and the state of its lanes, and that posture decides whether any booking, hold, activation, or boarding may proceed at all. A single bad weather log can cascade through closed lanes, expired tickets, and automatic refunds in one motion.

Because riders, operators, group hosts, and safety marshals all act on the same shared inventory at the same time, the system enforces immediate consistency: capacity ledgers are reconciled the instant a ticket is confirmed or released, derived counts are recomputed on every lane or weather change, and concurrent writers are protected by optimistic concurrency on the time block they compete for. All times are stored in UTC and evaluated against a logical clock so that date-driven behavior — pass expiry, daily redemption resets, time-block windows — is fully deterministic.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every authenticated request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes five roles, spelled exactly: `Anonymous`, `GuestPatron`, `GroupHost`, `ParkOperator`, and `SafetyMarshal`. A request that omits either header, or whose `X-User-Role` is not one of these declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The sole exceptions are the two bootstrap endpoints — registering a patron and creating a park — which accept unauthenticated callers. When a caller presents valid headers but the role is not permitted to invoke the targeted endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Two roles are **entity-backed**. When `X-User-Role` is `GuestPatron`, `X-User-ID` is the `id` of the acting `Patron`; ownership checks on any resource that references a patron compare the resource's `holder_patron_id` to `X-User-ID`. When `X-User-Role` is `GroupHost`, `X-User-ID` is likewise the `id` of the acting `Patron`; ownership checks on a group reservation compare the reservation's `host_patron_id` to `X-User-ID`. A `GuestPatron` acting on a ticket they do not hold, or a `GroupHost` acting on a reservation they do not host, is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

The remaining three roles are **opaque operator identities**. When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque bootstrap identifier not tied to any persisted entity; it may only register patrons and create parks. When `X-User-Role` is `ParkOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. When `X-User-Role` is `SafetyMarshal`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity, recorded but never compared against any entity's `id`. A `GuestPatron` books and holds their own tickets, season passes, waivers, and add-ons; a `GroupHost` owns the lifecycle of a party reservation; a `ParkOperator` runs lanes, time blocks, weather, conveyor clearing, and park and pass configuration; a `SafetyMarshal` owns waivers, equipment dispatch, gear-up, boarding, redemption, and add-on fulfillment.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by their creation timestamp (`created_at`) in ascending order.

Each list response carries these four fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Audit Fields

Most resources in the system carry a standard set of system-managed fields. Every such resource has an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, recording when the resource was first created. Resources that may be mutated after creation additionally carry an `updated_at` timestamp (same format, refreshed on every change) and a `version` integer that starts at 1 and increments by one on every mutation.

Two record types are append-only logs and therefore carry **only** `id` and `created_at` — they have no `updated_at` and no `version` because they are never mutated after creation: the weather reading (`WeatherLog`) and the refund record (`RefundEntry`). Every other resource — the park, lane, time block, session ticket, waiver, season pass, group reservation, equipment rental, conveyor turn, add-on, and patron — carries the full `id`, `created_at`, `updated_at`, and `version` set.

When a server-side reconciliation changes a resource's derived fields — for example when a lane state change recomputes a park's `open_lane_count` and `total_capacity_remaining`, or a ticket confirmation bumps a time block's `committed_rider_count` — that counts as a mutation: the affected resource's `updated_at` is refreshed and its `version` increments. Where a state-machine side effect explicitly calls for a version bump (notably on the park and on a time block), that bump is in addition to any other mutation bookkeeping.

### 2.5. Monetary Precision and Rounding

All monetary amounts are stored as integer cents — there are no fractional cents in stored fields. Where a calculation multiplies a price by a discount factor and the result is not a whole number of cents, the system rounds half up (a value exactly halfway between two cents rounds up to the larger cent). Each calculation below states exactly where in its sequence the single rounding step occurs; the rounding is applied at that point and nowhere else.

### 2.6. The Operational Posture Aggregate

The heart of the park's safety model is its `operational_posture`, a computed field on the park that is one of `OPEN`, `RESTRICTED`, or `CLOSED` and starts at `OPEN` when a park is created. Posture is not set directly by anyone; it is **derived** and recomputed from the most recent weather reading every time a weather log is appended or a lane changes state.

A single weather reading implies a posture (recorded on the reading as `derived_posture`) according to the park's two safety thresholds, `min_snow_depth_cm` (default 15) and `max_safe_wind_kph` (default 50). The rules, evaluated in this order: if the reading's `snow_depth_cm` is strictly less than the park's `min_snow_depth_cm`, the implied posture is `CLOSED`. Otherwise, if the reading's `wind_kph` is greater than or equal to the park's `max_safe_wind_kph` and its `snow_depth_cm` is greater than or equal to `min_snow_depth_cm`, the implied posture is `RESTRICTED`. Otherwise the implied posture is `OPEN`. In short: insufficient snow closes the park outright regardless of wind; sufficient snow with dangerous wind restricts it; sufficient snow with safe wind opens it. The park's `operational_posture` is then set to the posture implied by the latest reading.

Posture gates child operations. While the park's `operational_posture` is `CLOSED`, the following five operations are all rejected with `ERR_PARK_CLOSED` (HTTP 409): confirming a ticket, holding a group reservation, confirming a group reservation, activating a time block, and boarding a rider. Confirming a ticket and holding a group reservation additionally require the posture to be exactly `OPEN` — a posture of `RESTRICTED` blocks them too (see §3).

### 2.7. Capacity, Committed Riders, and the Park Ledger

The park exposes two reconciled denormalized counts. `open_lane_count` is the number of lanes belonging to the park whose `status` is `OPEN`, recomputed on every lane state change. `total_capacity_remaining` is the sum, over all `OPEN` lanes, of each lane's `rider_capacity_per_block`, minus the riders already committed for the active block; it is reconciled on every event that opens or closes a lane or commits or releases a rider.

Each time block tracks `committed_rider_count`: the number of riders committed into that block across all lanes, counting confirmed tickets and confirmed group seats. This count is the ledger that the capacity guard reads. The guard's rule is uniform: a commit may not push a time block's `committed_rider_count` above the sum of the capacities (`rider_capacity_per_block`) of the park's currently `OPEN` lanes. A commit that would breach that ceiling is rejected with `ERR_CAPACITY_EXCEEDED` (HTTP 409). This guard applies to three operations: confirming a ticket, confirming a shared-seats group reservation, and holding a shared-seats group reservation. Every commit increments the block's `committed_rider_count` and recomputes the park's `total_capacity_remaining`; every release (refund, expiry, cancellation) decrements it and recomputes again.

### 2.8. Optimistic Concurrency on Time Blocks

Two write operations compete directly for a time block's capacity, and both are protected by optimistic concurrency keyed on the time block's `version`. Confirming a ticket into a block requires the request body to carry `expected_time_block_version`, and that value must match the target time block's current `version`. If another writer has advanced the block's `version` since the client last read it — for example by confirming another ticket, which legitimately consumes a slot and bumps `committed_rider_count` — the confirm is rejected with `ERR_STALE_VERSION` (HTTP 412), because the client's view of remaining capacity is stale and proceeding could push the block past its open-lane capacity ceiling. Likewise, placing a hold on a group reservation requires the request body to carry `expected_time_block_version` matching the target time block's current `version`; if a competing writer has since held or confirmed seats or an exclusive lane in the same block (consuming capacity and bumping the block's `version`), the hold is rejected with `ERR_STALE_VERSION` (HTTP 412). These are the only two endpoints that take a version field; no other endpoint accepts or checks one.

Each successful ticket confirm and each successful group hold increments the target time block's `version` by one, which is precisely what makes a stale follow-up writer's `expected_time_block_version` fail to match.

### 2.9. Nested Path Resolution and Left-to-Right Validation

Several endpoints address a child through its parent — for instance, listing or creating lanes, time blocks, or weather logs under a specific park. For any such request, the system validates the path identifiers strictly left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier in the path that names no existing resource. A lane-creation request under a non-existent park therefore fails on the park before the body is examined. This same left-to-right existence rule governs every body-referenced foreign key as well: any referenced resource that does not exist yields `ERR_NOT_FOUND`.

### 2.10. Validation Ordering

When several checks could fire on one request, they are evaluated in a fixed priority order so that the returned error is deterministic. The order is: (1) authentication — headers present and the role declared, else `ERR_UNAUTHENTICATED`; (2) authorization — the role may call this endpoint, else `ERR_FORBIDDEN_ROLE`; (3) existence — every path- and body-referenced resource exists, validated left to right, else `ERR_NOT_FOUND`; (4) ownership — an entity-backed actor owns the targeted ticket or reservation, else `ERR_NOT_RESOURCE_OWNER`; (5) state — the target is in a state from which the requested transition is defined, else `ERR_INVALID_STATE`; (6) optimistic concurrency — on the two OCC endpoints, `expected_time_block_version` matches the block's current `version`, else `ERR_STALE_VERSION`; (7) closed-park gating — a `CLOSED` posture blocks the gated operations, else `ERR_PARK_CLOSED`. After these come the domain-specific business checks described throughout §3 — waiver presence, guardian requirement, height minimum, lane-turn overlap, block window, lane availability, pass daily limit, pass validity, and the capacity guard — and finally the catch-all request-shape check that required fields are present and well-typed, enum values are in their declared sets, and numeric ranges are honored, which otherwise yields `ERR_INVALID_REQUEST` (HTTP 422). Concretely, an authentication failure is reported before an authorization failure, a missing resource before an ownership failure, an illegal state before a stale version, and a stale version before a closed-park rejection.

### 2.11. The Logical Clock and Daily Sweep

All date, window, and expiry math is evaluated against a logical clock, never against real wall-clock time. Before any clock call is made, the clock reads `2026-03-01T00:00:00Z`, and it never falls back to wall-clock time. An operator may advance the clock by supplying a `to_iso8601` instant. Advancing the clock runs a daily sweep: when the UTC calendar date advances, every season pass's `redemptions_today_count` is reset to 0, and any season pass currently `ACTIVE` whose `valid_until` is at or before the new clock instant is flipped to `EXPIRED`. The sweep also expires a season pass that is `SUSPENDED` once the clock reaches or passes its `valid_until`.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Park: Lanes, Time Blocks, and Configuration

A park is the hierarchical root of everything. Creating one is a bootstrap action requiring no authentication; the caller supplies a display `name` and may optionally supply a `timezone_offset_minutes` (a fixed UTC offset in minutes used only for display, defaulting to 0, since all stored times are UTC), a list of `resident_zip_prefixes` (zip-code prefixes that qualify a patron as a resident, possibly empty), a `min_snow_depth_cm` (defaulting to 15), and a `max_safe_wind_kph` (defaulting to 50). A freshly created park has `operational_posture` of `OPEN`, an `open_lane_count` of 0, and a `total_capacity_remaining` of 0.

A `ParkOperator` builds out the park's physical inventory. Each lane is created under a park with a human `label` (such as "Lane A"), a `rider_capacity_per_block` (the maximum concurrent riders the lane admits within one time block, at least 1), and a `conveyor_cycle_seconds` (the seconds one conveyor-lift cycle takes, at least 1). A lane belongs to its park through `park_id`. A new lane begins with `status` of `OPEN` and a null `closure_reason`. Creating a lane recomputes the park's `open_lane_count` and `total_capacity_remaining` and increments the park's `version` by one.

A lane moves through `OPEN`, `GROOMING`, and `CLOSED`, and its `closure_reason` is one of `WEATHER`, `MAINTENANCE`, `GROUP_RENTAL`, or null while open. Taking a lane down for grooming — the `OPEN → GROOMING` transition — is permitted only when the lane is `OPEN` and no `ACTIVE` time block has committed riders on that lane; success sets `status` to `GROOMING`, sets `closure_reason` to `MAINTENANCE`, and bubbles up a recompute of the park's `open_lane_count` and `total_capacity_remaining`. Returning a groomed lane to service — `GROOMING → OPEN` — requires the lane to be `GROOMING` and the park's posture to be anything other than `CLOSED`; it clears `closure_reason` to null and bubbles up the same recompute. Closing a lane manually — `OPEN → CLOSED` — requires the lane to be `OPEN`, sets `closure_reason` to `MAINTENANCE`, and cascades (see §3.6). Reopening a closed lane — `CLOSED → OPEN` — requires the lane to be `CLOSED` and the park's posture to be other than `CLOSED`, and clears `closure_reason`. A transition requested from a state where it is not defined is rejected with `ERR_INVALID_STATE`.

Time blocks are the schedule grid. A `ParkOperator` creates a block under a park with a `starts_at` and `ends_at`; the block represents the half-open UTC interval beginning inclusively at `starts_at` and ending exclusively at `ends_at`, and `ends_at` must be strictly after `starts_at`. A block belongs to its park through `park_id`, begins with `status` of `SCHEDULED`, and tracks `committed_rider_count` starting at 0. Activating a block — `SCHEDULED → ACTIVE` — requires the block to be `SCHEDULED`, the park's posture to be other than `CLOSED`, and the logical clock to fall within the block's window, meaning the clock instant is at or after `starts_at` and strictly before `ends_at`; activating outside that window is rejected with `ERR_BLOCK_WINDOW_CLOSED` (HTTP 409). Sweeping a block — `ACTIVE → SWEPT` — requires the block to be `ACTIVE` and is terminal; its cascades are described in §3.6.

### 3.2. Patrons, Waivers, and Resident Status

Anyone may register a `Patron` — a bootstrap action with no authentication — by supplying a `full_name`, a `zip_code`, and a `birthdate` (a UTC instant used to derive a rider's age when a ticket does not declare one). A patron's `zip_code` is matched against the park's `resident_zip_prefixes` to determine resident status.

Before a rider can take to the hill, an `ACTIVE` waiver must be on file. A waiver is signed for a patron at a park, recording the covered `patron_id`, the `park_id` where it is valid, the `signed_at` instant, and, when required, a `guardian_name`. A waiver begins with `status` of `ACTIVE` and may be revoked by a `SafetyMarshal`, moving it to `REVOKED`; revocation requires the waiver to be `ACTIVE`. Once a waiver is revoked, any subsequent confirm or board for that holder at that park fails for lack of an active waiver unless another `ACTIVE` waiver covers them. Two safety checks read the waiver: confirming a ticket and boarding a rider both require an `ACTIVE` waiver to exist for the holder at the park, and the absence of one is rejected with `ERR_WAIVER_MISSING` (HTTP 409). Separately, a minor rider — one whose `rider_age_years` is less than 18 — requires that the holder's `ACTIVE` waiver carry a non-null `guardian_name`; confirming a ticket for a minor without a guardian signatory is rejected with `ERR_GUARDIAN_REQUIRED` (HTTP 422).

### 3.3. Season Passes and Resident Pricing Eligibility

A season pass is issued to a patron for a park, recording the `park_id`, the `holder_patron_id`, a `tier` of `SILVER`, `GOLD`, or `RESIDENT_GOLD`, an inclusive `valid_from`, and an exclusive `valid_until` that must be strictly after `valid_from`. A pass tracks `redemptions_today_count` (starting at 0, reset by the daily sweep when the clock's date rolls) and a `status` that starts `ACTIVE`. A `ParkOperator` may suspend an active pass — `ACTIVE → SUSPENDED` — which requires it to be `ACTIVE`; thereafter any ticket creation against that pass is refused as not valid. The daily sweep flips a pass to `EXPIRED` from either `ACTIVE` or `SUSPENDED` once the clock reaches or passes its `valid_until`.

When a ticket is created against a season pass, two pass guards run. First, the pass must currently be valid: its `status` must be `ACTIVE` and the logical clock must fall within the pass window — at or after `valid_from` and strictly before `valid_until`; otherwise the creation is rejected with `ERR_PASS_NOT_VALID` (HTTP 409). Second, the pass's daily redemption allowance must not be exceeded for the current clock date. The allowance depends on tier: a `SILVER` pass permits 2 redemptions per day, a `GOLD` pass permits 4 per day, and a `RESIDENT_GOLD` pass permits 6 per day. A creation that would carry `redemptions_today_count` past the tier's allowance is rejected with `ERR_PASS_DAILY_LIMIT` (HTTP 409).

### 3.4. Booking a Ticket: Creation, Pricing, and Confirmation

A `GuestPatron` reserves a seat by creating a `SessionTicket`, which admits one rider to one block at one park. The creation payload carries the `park_id` the ticket admits to, the `time_block_id` it is committed into, the `holder_patron_id` of the guest, the declared `rider_height_cm` (the rider's height in centimeters, at least 30), and the declared `rider_age_years` (at least 0). Optionally it may carry a `season_pass_id` (set when the ticket is issued via a pass redemption, otherwise null) and an `upgraded_from_ticket_id` (a self-reference to the ticket this one replaced on an upgrade, otherwise null). A new ticket starts with `lifecycle_state` of `RESERVED` and `checkin_state` of `NOT_CHECKED_IN`; these two dimensions evolve independently. At creation the system also computes `is_resident` — true when the holder's zip prefix matches the park's `resident_zip_prefixes` at issuance, false otherwise — and computes the ticket's `base_price_cents`. When a `season_pass_id` is supplied, creation also enforces the pass validity and daily-limit guards of §3.3 and increments that pass's `redemptions_today_count` by one.

Pricing of `base_price_cents` follows a pinned four-step sequence. First, pick the base by age tier: if `rider_age_years` is less than 6, the base is 1500 cents; otherwise if `rider_age_years` is less than 13, the base is 2500 cents; otherwise if `rider_age_years` is at least 65, the base is 2000 cents; otherwise (ages 13 through 64) the base is 3500 cents. Second, start a discount factor at 1.0 and, if the ticket was issued via a season pass, multiply that factor by one minus the pass discount — 0.10 for a `SILVER` pass, 0.25 for a `GOLD` pass, or 0.40 for a `RESIDENT_GOLD` pass. Third, apply the resident discount: if the holder is a resident and the pass tier is not `RESIDENT_GOLD`, multiply the factor by one minus 0.05; the resident 5% stacks on top of the pass discount except when the pass is already `RESIDENT_GOLD`, in which case the resident discount is not applied. Fourth, multiply the chosen base by the final discount factor and round the result half up to whole cents — this single rounding is applied exactly once, after both discount factors have multiplied, and nowhere earlier. A walk-up ticket with no `season_pass_id` skips the pass-discount step entirely, so only the resident 5% can apply.

Confirming a ticket — the `RESERVED → CONFIRMED` lifecycle transition — is performed by the holding `GuestPatron` and is the system's busiest checkpoint. It requires the ticket to be in `RESERVED` lifecycle, an `ACTIVE` waiver to exist for the holder at the park, the park's posture to be exactly `OPEN`, and the capacity guard to hold — the target block's `committed_rider_count` plus one must not exceed the sum of the open lanes' capacities. The request must also carry `expected_time_block_version` matching the block's current `version` (see §2.8). On success the ticket's `lifecycle_state` becomes `CONFIRMED`, the block's `committed_rider_count` rises by one, the block's `version` increments by one, and the park's `total_capacity_remaining` is recomputed. The guardian rule of §3.2 also applies here for minor riders.

A confirmed ticket may be refunded by its holder — the `CONFIRMED → REFUNDED` transition — but only while the ticket is `CONFIRMED` and its `checkin_state` is still `NOT_CHECKED_IN`. A refund sets `lifecycle_state` to `REFUNDED`, decrements the block's `committed_rider_count` by one, recomputes the park's `total_capacity_remaining`, and writes a `RefundEntry` whose `reason` is `PATRON_CANCEL` and whose `amount_cents` equals the ticket's `base_price_cents`. If the ticket carried a `season_pass_id`, the refund also releases the redemption slot by decrementing that pass's `redemptions_today_count` by one.

### 3.5. Check-In: Gearing Up, Boarding, Redeeming, and Conveyor Turns

The check-in dimension (`checkin_state`) advances independently of lifecycle until the final redemption. A `SafetyMarshal` gears up a rider — `NOT_CHECKED_IN → GEARED_UP` — which requires the ticket's `checkin_state` to be `NOT_CHECKED_IN`, its `lifecycle_state` to be `CONFIRMED`, and at least one `DISPATCHED` equipment rental of `equipment_type` `TUBE` to exist for the ticket. Gearing up with a tube also enforces the height minimum: the rider's `rider_height_cm` must be at least 92 centimeters, and a shorter rider is rejected with `ERR_HEIGHT_BELOW_MIN` (HTTP 422).

Equipment is dispatched by a `SafetyMarshal` against a ticket. Each rental records the `ticket_id` it is dispatched against, an `equipment_type` of `TUBE`, `HELMET`, or `BOOTS`, and, only when the type is `TUBE`, a `tube_size` of `SMALL`, `MEDIUM`, `LARGE`, or null. A rental starts in `state` `DISPATCHED` and may be moved by a marshal to `RETURNED` or `DAMAGED`, each requiring the rental to be currently `DISPATCHED`.

Boarding a rider — `GEARED_UP → ON_LANE` — is performed by a `SafetyMarshal` and carries a `lane_id` (the lane to board) and a `boarded_at` instant. It requires the ticket's `checkin_state` to be `GEARED_UP` and the target lane's `status` to be `OPEN`. Boarding also revalidates the active-waiver requirement and is blocked when the park posture is `CLOSED`. Boarding creates a `ConveyorTurn` in `state` `BOARDED` on the lane, recording the `lane_id`, the `time_block_id`, the rider's `ticket_id`, the `boarded_at` instant, and a computed `cleared_at` equal to `boarded_at` plus the lane's `conveyor_cycle_seconds` (added as seconds) — the instant the turn clears the lift head. A lane admits only one turn at a time: a new turn's half-open interval from `boarded_at` (inclusive) to `cleared_at` (exclusive) must not overlap any existing `BOARDED` turn on the same lane. Adjacency is allowed — a new turn whose `boarded_at` exactly equals an existing turn's `cleared_at` does not overlap, because the interval is half-open with zero buffer — but any true overlap is rejected with `ERR_LANE_TURN_OVERLAP` (HTTP 409).

Once a turn has run its cycle, a `ParkOperator` clears it — `BOARDED → CLEARED` — which requires the turn to be `BOARDED` and the logical clock to be at or after the turn's `cleared_at`. Clearing the turn does not by itself move the rider's check-in state back; advancing a rider from on-lane back to geared-up is a separate dismount action, not automatic.

Redemption is the lifecycle finale a `SafetyMarshal` performs — `CONFIRMED → REDEEMED` — and is the one point where the two ticket dimensions meet: it requires the ticket's `lifecycle_state` to be `CONFIRMED`, its `checkin_state` to be `ON_LANE`, and the ticket's time block to be `ACTIVE`. The states `REDEEMED`, `EXPIRED`, and `REFUNDED` are all terminal lifecycle states.

### 3.6. Closures, Cascades, and Refund Reconciliation

Closures ripple downward, and the system reconciles every affected ledger in one motion. The trigger for posture change is a new weather reading: a `ParkOperator` appends a reading carrying its `observed_at` instant, the measured `snow_depth_cm` (at least 0), and the measured `wind_kph` (at least 0). The reading's `derived_posture` is computed per §2.6, and the park's `operational_posture` is recomputed from the latest reading; appending a reading increments the park's `version` by one.

When the recompute drives the park to `CLOSED` (latest reading implies `CLOSED`), the cascade fires: every lane currently `OPEN` or `GROOMING` is forced to `CLOSED` with `closure_reason` `WEATHER`; and for each lane so closed, every `CONFIRMED` session ticket committed to that lane in the active block is forced to `EXPIRED`, and each such weather-expiry writes a `RefundEntry` whose `reason` is `WEATHER_CLOSURE` and whose `amount_cents` equals that ticket's `base_price_cents`. The recompute then refreshes the park's `open_lane_count` and `total_capacity_remaining`. When the recompute drives the park to `RESTRICTED` (latest reading implies `RESTRICTED`), the park's posture becomes `RESTRICTED` and `total_capacity_remaining` is recomputed over open lanes, with no lane closures. When a later reading clears the thresholds (latest reading implies `OPEN`), the park returns to `OPEN`; note that lanes are **not** auto-reopened after a weather closure — an operator must reopen each lane explicitly.

A manual lane close — the `OPEN → CLOSED` lane transition — carries the same downward cascade scoped to that one lane: every `CONFIRMED` session ticket committed to the lane in an active or scheduled block is forced to `EXPIRED`, each creating a `RefundEntry`, and the park's `open_lane_count` and `total_capacity_remaining` are recomputed. Whenever a confirmed ticket is forced to `EXPIRED` by a closure cascade, the block's `committed_rider_count` is decremented by one and the park's `total_capacity_remaining` is recomputed; when the expiry was triggered by a weather closure, the `WEATHER_CLOSURE` refund is written.

Sweeping a block is the other terminal cascade. When a `ParkOperator` sweeps an active block — `ACTIVE → SWEPT` — every `CONFIRMED` ticket in that block that is still `NOT_CHECKED_IN` is treated as a no-show and forced to `EXPIRED` with **no** refund (a no-show forfeits), and that expiry releases its committed slot: `committed_rider_count` is decremented and park aggregates recomputed. The sweep also flags every `REDEEMED` ticket's `DISPATCHED` equipment rental for return reconciliation, though the rental's `state` stays `DISPATCHED` until it is actually returned.

Refund records are append-only. Each `RefundEntry` references either a `ticket_id` (for a ticket refund, with `group_reservation_id` null) or a `group_reservation_id` (for a group refund, with `ticket_id` null), carries a positive `amount_cents`, and records a `reason` of `WEATHER_CLOSURE`, `PATRON_CANCEL`, or `GROUP_CANCEL`.

### 3.7. Group Parties: Holds, Revisions, and the Deposit

A `GroupHost` books a party as a `GroupReservation` against a park and block, recording the `park_id`, the `host_patron_id`, the `time_block_id` the party occupies, a `rental_type` of `SHARED_SEATS` or `EXCLUSIVE_LANE`, and a `party_size` of at least 2. For an exclusive-lane booking the payload must carry a non-null `lane_id` naming the lane reserved for exclusive use; for a shared-seats booking the payload must **not** carry a `lane_id`. A reservation that carries a `lane_id` for shared seats, or omits one for an exclusive lane, is rejected with `ERR_INVALID_REQUEST` (HTTP 422). A new reservation starts in `state` `DRAFT` with `deposit_cents` of 0.

Holding a reservation — `DRAFT → HELD` — is where capacity is reserved and the deposit is computed. It requires the reservation to be `DRAFT` and the park's posture to be exactly `OPEN`. For an exclusive-lane party, the target lane must be `OPEN` and not already held by another reservation in the same block; a lane already closed or held for another group in that block is rejected with `ERR_LANE_UNAVAILABLE` (HTTP 409). For a shared-seats party, the capacity guard applies — the block's `committed_rider_count` plus `party_size` must not exceed the sum of open-lane capacities, else `ERR_CAPACITY_EXCEEDED`. The hold request must also carry `expected_time_block_version` matching the block's current `version` (see §2.8). On a successful hold, the reservation's `state` becomes `HELD`, the deposit is computed into `deposit_cents`, and for an exclusive-lane party the reserved lane is taken to `CLOSED` with `closure_reason` `GROUP_RENTAL`, bubbling up a recompute of the park's `open_lane_count` and `total_capacity_remaining`. A successful hold also increments the block's `version` by one.

The deposit computation reads three inputs with a non-linear interaction: `party_size`, `rental_type`, and a per-head rate that itself tiers on `party_size`. First select the per-head rate by party-size tier — and the **whole** party bills at the tier its size falls into, not marginally across tier boundaries: a party of 5 or fewer bills at 3000 cents per head, a party of 6 through 12 bills at 2600 cents per head, and a party of 13 or more bills at 2200 cents per head. The seats subtotal is that per-head rate multiplied by `party_size`. For an exclusive-lane party the deposit is the seats subtotal plus a flat 20000 cents exclusive-lane charge. For a shared-seats party the deposit is the larger of the seats subtotal and a floor of 8000 cents.

A held reservation can be revised for re-quote — `HELD → DRAFT` — forming a draft-to-held-to-draft loop; revising requires the reservation to be `HELD`, and for an exclusive-lane party it releases the held lane back to `OPEN` with `closure_reason` cleared to null and bubbles up the park recompute. Confirming a held reservation — `HELD → CONFIRMED` — requires it to be `HELD` and the park's posture to be exactly `OPEN`; for a shared-seats party, confirmation commits the seats by raising the block's `committed_rider_count` by `party_size` and recomputing the park's `total_capacity_remaining` (and is subject to the capacity guard). Cancelling a reservation — from either `HELD` or `CONFIRMED` to `CANCELLED` — requires the reservation to be in that respective state; it releases whatever was held (a shared-seats confirmation gives its `party_size` back to `committed_rider_count`; an exclusive-lane party releases its lane back to `OPEN` with `closure_reason` cleared), recomputes park aggregates, and writes a `RefundEntry` whose `reason` is `GROUP_CANCEL` and whose `amount_cents` equals the reservation's `deposit_cents`. The `CANCELLED` state is terminal.

### 3.8. Add-Ons: Food, Drinks, and Upgrades

A `GuestPatron` or `SafetyMarshal` orders an add-on against a ticket, recording the `park_id` it is sold at, the `ticket_id` it attaches to, a `category` of `FOOD`, `RENTAL_UPGRADE`, or `HOT_DRINK`, a `unit_price_cents` (per-unit list price, at least 0), and a `quantity` (at least 1). A new add-on starts in `state` `ORDERED` with `line_total_cents` of 0, and may be moved by a marshal to `FULFILLED` or by a guest or marshal to `VOIDED`, each transition requiring the add-on to be `ORDERED`.

The `line_total_cents` is computed at order time with a pinned rounding order: discount the per-unit price first, round per unit, and only then multiply by quantity. Start from the raw `unit_price_cents`. If the linked ticket's holder has an `ACTIVE` `GOLD` or `RESIDENT_GOLD` season pass and the `category` is `FOOD`, the per-unit price is multiplied by one minus 0.15. Otherwise, if the ticket's `is_resident` is true and the `category` is `HOT_DRINK`, the per-unit price is multiplied by one minus 0.10. Otherwise the per-unit price is unchanged. Round that discounted per-unit price half up to whole cents first, then multiply the rounded per-unit amount by `quantity` to get `line_total_cents`. The rounding happens once, per unit, before the multiplication — never after — so the final product is exact.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource — chiefly the state transitions — return `200 OK`. The clock-setting capability also returns `200 OK`. Reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/patrons` | Register a patron (bootstrap; no auth) | Anonymous, ParkOperator |
| GET | `/patrons/{id}` | Fetch a patron | GuestPatron, GroupHost, ParkOperator, SafetyMarshal |
| POST | `/parks` | Create a park (bootstrap; no auth) | Anonymous, ParkOperator |
| GET | `/parks/{id}` | Fetch a park including computed posture and capacity | GuestPatron, GroupHost, ParkOperator, SafetyMarshal |
| GET | `/parks` | List parks | GuestPatron, GroupHost, ParkOperator, SafetyMarshal |
| POST | `/parks/{id}/lanes` | Create a lane under a park | ParkOperator |
| GET | `/parks/{id}/lanes` | List lanes for a park | GuestPatron, GroupHost, ParkOperator, SafetyMarshal |
| GET | `/lanes/{id}` | Fetch a lane | GuestPatron, GroupHost, ParkOperator, SafetyMarshal |
| POST | `/lanes/{id}/groom` | Move a lane into grooming | ParkOperator |
| POST | `/lanes/{id}/reopen` | Return a groomed or closed lane to service | ParkOperator |
| POST | `/lanes/{id}/close` | Close a lane (maintenance) and cascade ticket expiry | ParkOperator |
| POST | `/parks/{id}/time-blocks` | Create a time block under a park | ParkOperator |
| GET | `/parks/{id}/time-blocks` | List time blocks for a park | GuestPatron, GroupHost, ParkOperator, SafetyMarshal |
| GET | `/time-blocks/{id}` | Fetch a time block including committed rider count | GuestPatron, GroupHost, ParkOperator, SafetyMarshal |
| POST | `/time-blocks/{id}/activate` | Activate a scheduled block | ParkOperator |
| POST | `/time-blocks/{id}/sweep` | Sweep an active block and expire no-shows | ParkOperator |
| POST | `/parks/{id}/weather-logs` | Append a weather reading and recompute posture | ParkOperator |
| GET | `/parks/{id}/weather-logs` | List weather readings for a park | GuestPatron, GroupHost, ParkOperator, SafetyMarshal |
| POST | `/waivers` | Sign a waiver for a patron at a park | GuestPatron, SafetyMarshal |
| GET | `/waivers` | List waivers (filter by patron and/or park) | GuestPatron, SafetyMarshal, ParkOperator |
| GET | `/waivers/{id}` | Fetch a waiver | GuestPatron, SafetyMarshal, ParkOperator |
| POST | `/waivers/{id}/revoke` | Revoke a waiver | SafetyMarshal |
| POST | `/season-passes` | Issue a season pass | ParkOperator, GuestPatron |
| GET | `/season-passes` | List season passes (filter by holder and/or park) | GuestPatron, ParkOperator |
| GET | `/season-passes/{id}` | Fetch a season pass | GuestPatron, ParkOperator |
| POST | `/season-passes/{id}/suspend` | Suspend an active pass | ParkOperator |
| POST | `/tickets` | Create a session ticket | GuestPatron |
| GET | `/tickets/{id}` | Fetch a ticket | GuestPatron, SafetyMarshal, ParkOperator |
| GET | `/tickets` | List tickets (filter by holder, park, block, pass, upgrade source) | GuestPatron, SafetyMarshal, ParkOperator |
| POST | `/tickets/{id}/confirm` | Confirm a reserved ticket (OCC on the block) | GuestPatron |
| POST | `/tickets/{id}/refund` | Refund a confirmed ticket | GuestPatron |
| POST | `/tickets/{id}/gear-up` | Gear up a confirmed rider | SafetyMarshal |
| POST | `/tickets/{id}/board` | Board a geared-up rider and create a conveyor turn | SafetyMarshal |
| POST | `/tickets/{id}/redeem` | Redeem an on-lane ticket | SafetyMarshal |
| POST | `/equipment-rentals` | Dispatch equipment against a ticket | SafetyMarshal |
| GET | `/equipment-rentals` | List equipment rentals (filter by ticket) | SafetyMarshal, ParkOperator, GuestPatron |
| GET | `/equipment-rentals/{id}` | Fetch an equipment rental | SafetyMarshal, ParkOperator, GuestPatron |
| POST | `/equipment-rentals/{id}/return` | Return a dispatched rental | SafetyMarshal |
| POST | `/equipment-rentals/{id}/report-damage` | Report a dispatched rental as damaged | SafetyMarshal |
| GET | `/conveyor-turns` | List conveyor turns (filter by lane, block, ticket) | ParkOperator, SafetyMarshal |
| GET | `/conveyor-turns/{id}` | Fetch a conveyor turn | ParkOperator, SafetyMarshal |
| POST | `/conveyor-turns/{id}/clear` | Clear a boarded turn after its cycle | ParkOperator |
| POST | `/group-reservations` | Create a group reservation | GroupHost |
| GET | `/group-reservations` | List group reservations (filter by host, park, block, lane) | GroupHost, ParkOperator |
| GET | `/group-reservations/{id}` | Fetch a group reservation | GroupHost, ParkOperator |
| POST | `/group-reservations/{id}/hold` | Hold a draft reservation (OCC on the block) | GroupHost |
| POST | `/group-reservations/{id}/revise` | Revise a held reservation back to draft | GroupHost |
| POST | `/group-reservations/{id}/confirm` | Confirm a held reservation | GroupHost |
| POST | `/group-reservations/{id}/cancel` | Cancel a held or confirmed reservation | GroupHost |
| POST | `/add-ons` | Order an add-on against a ticket | GuestPatron, SafetyMarshal |
| GET | `/add-ons` | List add-ons (filter by ticket and/or park) | GuestPatron, SafetyMarshal, ParkOperator |
| GET | `/add-ons/{id}` | Fetch an add-on | GuestPatron, SafetyMarshal, ParkOperator |
| POST | `/add-ons/{id}/fulfill` | Fulfill an ordered add-on | SafetyMarshal |
| POST | `/add-ons/{id}/void` | Void an ordered add-on | GuestPatron, SafetyMarshal |
| GET | `/refund-entries` | List refund entries (filter by ticket and/or group reservation) | GuestPatron, GroupHost, ParkOperator |
| GET | `/refund-entries/{id}` | Fetch a refund entry | GuestPatron, GroupHost, ParkOperator |
| POST | `/_clock/set_current_utc` | Set the logical clock and run the daily sweep | ParkOperator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_PARK_CLOSED` | 409 |
| `ERR_WAIVER_MISSING` | 409 |
| `ERR_GUARDIAN_REQUIRED` | 422 |
| `ERR_HEIGHT_BELOW_MIN` | 422 |
| `ERR_LANE_TURN_OVERLAP` | 409 |
| `ERR_BLOCK_WINDOW_CLOSED` | 409 |
| `ERR_LANE_UNAVAILABLE` | 409 |
| `ERR_PASS_DAILY_LIMIT` | 409 |
| `ERR_PASS_NOT_VALID` | 409 |
| `ERR_CAPACITY_EXCEEDED` | 409 |
| `ERR_INVALID_REQUEST` | 422 |

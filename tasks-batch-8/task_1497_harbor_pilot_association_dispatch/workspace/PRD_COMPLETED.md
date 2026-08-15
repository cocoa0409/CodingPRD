# Harbor Pilot Dispatch API — Product Requirements Document

## 1. Introduction

A state harbor pilots association operates as a member-owned cooperative: licensed pilots take turns on a rotation board, dispatchers match incoming vessel movement orders to rested and properly-endorsed pilots, pilot boats ferry pilots to and from ships, and the association invoices vessel agents for each completed act of pilotage before distributing net revenue to members according to their cooperative shares. The operational problem this system solves is that every one of those steps interacts with every other — a pilot cannot be dispatched while fatigued, an invoice cannot be finalized while an incident on the same assignment is still under review, and a substantiated incident must pull the pilot off the board and recall any work they were holding, all without losing track of who owes what to whom.

This document specifies the Harbor Pilot Dispatch API, a single REST surface mounted under `/pilotage` that governs the full cycle: vessel order intake with provisional tariff quotation, rotation-driven dispatch with fatigue and license gating, in-service tracking from launch to boarding to completion, final invoice composition with detention and delay extras, incident investigation with a suspension cascade, apprentice training progression, and periodic revenue distribution with an association levy. A logical clock drives all temporal reasoning — tariff schedule effectiveness, endorsement currency, rest expiry, and the rolling seven-day duty window — so the system is deterministic under test and the association can replay any period exactly as it happened.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, protocols, and cross-cutting invariants that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID` identifies the acting user, and `X-User-Role` declares their operational capacity. The system recognizes exactly six roles: `AssociationAdmin`, `Dispatcher`, `Pilot`, `VesselAgent`, `FinanceOfficer`, and `Investigator`. A request missing either header, or carrying a role outside this enumeration, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted on the targeted endpoint, or that fails an ownership check, is rejected with `ERR_FORBIDDEN` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Pilot`, `X-User-ID` is the `id` of the acting `Pilot`; ownership checks on any resource that references a `Pilot` compare the resource's foreign-key field to `X-User-ID` — a pilot may start, board, or complete only assignments whose `pilot_id` equals their `X-User-ID`, and may report incidents only on their own assignments. When `X-User-Role` is `AssociationAdmin`, `Dispatcher`, `VesselAgent`, `FinanceOfficer`, or `Investigator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for a `VesselAgent`, the identifier is captured at order intake as the order's `agent_id` and later compared against `X-User-ID` on amendment and cancellation — but for the remaining roles the server does not compare it to any entity's `id`.

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

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_` followed by 20 random alphanumeric characters.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, stamped from the logical clock (§2.4) rather than wall-clock time.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints; `has_more` is true exactly when `offset + limit` is less than `total_count`.

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

Requests to an unknown path — or to a known path with an unsupported method — are answered with `ERR_NOT_FOUND` (HTTP 404) in this same envelope; an unexpected server failure surfaces `ERR_INTERNAL` (HTTP 500).

---

### 2.3. Pagination

List endpoints are paginated through query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. A non-integer or out-of-range `limit` or `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp (`created_at`) in ascending order, with ties on equal `created_at` broken by creation order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock

All temporal reasoning in the system — ETA validation, endorsement currency, rest expiry, rolling duty windows, tariff schedule resolution, and distribution window membership — is evaluated against a server-held **logical clock**, never against wall-clock time. On startup, before any explicit set, the logical clock reads `2026-08-01T00:00:00Z`; the server must not fall back to wall-clock time under any circumstances. An `AssociationAdmin` advances the clock through an admin-only test-driving capability that accepts a `to_iso8601` instant — any parseable ISO 8601 instant is accepted, including one earlier than the current reading — and returns `200 OK` with the resulting `current_utc` value. Advancing the clock re-resolves tariff schedule statuses (a schedule whose `effective_from` has been reached may become `ACTIVE`, superseding its predecessor) and can make rested pilots newly eligible for dispatch without any other write occurring.

### 2.5. Common Resource Properties

Every top-level resource — pilots, endorsements, rotation entries, vessel orders, pilot boats, assignments, invoices, incidents, apprentices, tariff schedules, and distribution runs — carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits, set when the resource is first created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on any modification of the resource.
- `version` (integer): a system-managed integer that starts at 1 when the resource is created and increments by exactly one on every mutation of the resource, including mutations driven by cascading side effects.

Datetime-valued fields on resources — the system-managed `created_at` and `updated_at` above, and domain instants such as the order's `eta`, the pilot's `rest_until`, an endorsement's `expires_at`, an assignment's `scheduled_start`/`scheduled_end`/`actual_start`/`actual_end`, an invoice's `finalized_at`, a tariff schedule's `effective_from`, and a distribution run's `period_start`/`period_end` — are serialized in responses as ISO 8601 UTC timestamps with three fractional digits (for example, `2026-08-11T00:00:00.000Z`); a field whose instant is unset serializes as `null`.

Whenever an operation mutates a resource — directly or as a side effect of a transition on another resource — that resource's `updated_at` is refreshed and its `version` is incremented.

### 2.6. Monetary Values and Rounding

All monetary amounts are integer counts of cents; the API never exposes fractional cents. Wherever a calculation produces a non-integer intermediate (a percentage levy, a per-share allocation, a surcharge multiplication), the value is rounded **half-up** to the nearest integer cent. Two rounding orders are pinned and must not be interchanged. In invoice composition, each fee component — base, detention, delay — is individually rounded to integer cents first, and only then are the components summed into the invoice total; summing first and rounding once is forbidden. In revenue distribution, each pilot's per-share allocation is rounded half-up first, and the resulting remainder against the net pool is reconciled one cent at a time (see §3.8). Evaluation averages for apprentices are carried at two decimal places, rounded half-up on each recorded score.

### 2.7. Optimistic Concurrency Control

Two write endpoints require the caller to present the version of the parent resource they last observed, guarding against silently overwriting a newer state the client never saw. Amending a vessel order requires `expected_order_version` in the request body, carrying the client's last observed `version` of the target order. If the order's current `version` differs — because another writer amended the order in the meantime — the amendment is rejected with `ERR_STALE_VERSION` (HTTP 412). Issuing an endorsement to a pilot requires `expected_pilot_version`, carrying the client's last observed `version` of that pilot; a mismatch — for example because another writer's same-class endorsement legitimately superseded the one the client believed was current — is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints not named here do not accept a version field.

### 2.8. Validation Order and Existence Checks

Every request passes through a fixed validation pipeline, and the relative priority matters because it determines which error a multiply-invalid request surfaces. Authentication comes first: header presence and role membership (`ERR_UNAUTHENTICATED`), then role-permission and ownership checks (`ERR_FORBIDDEN`). Existence of every referenced resource — path identifiers and body-supplied identifiers alike, covering orders, assignments, pilots, boats, invoices, incidents, apprentices, distribution runs, and endorsements — is validated next, strictly left-to-right across the request, with the first missing reference yielding `ERR_NOT_FOUND`. Optimistic-concurrency checks (`ERR_STALE_VERSION`) follow existence. State-machine guards come after that — the generic from-state guard (`ERR_INVALID_STATE`) plus the order-specific guards `ERR_ORDER_LOCKED` and `ERR_ORDER_NOT_DISPATCHABLE`. Business-safety checks on an explicit reassign pilot are evaluated in a pinned order: license currency first (`ERR_LICENSE_NOT_CURRENT`), then tonnage cap (`ERR_TONNAGE_EXCEEDS_ENDORSEMENT`), then rest (`ERR_FATIGUE_REST_ACTIVE`), then the rolling duty limit (`ERR_FATIGUE_DUTY_LIMIT`) — so an unlicensed pilot surfaces the license error rather than being masked by a fatigue failure. Remaining business rules follow: selector pool emptiness (`ERR_NO_ELIGIBLE_PILOT`, `ERR_NO_ELIGIBLE_BOAT`), apprentice gating (`ERR_READINESS_NOT_MET`, `ERR_EXAM_NOT_PASSED`, `ERR_APPRENTICE_NOT_ENROLLED`), temporal rules (`ERR_ETA_IN_PAST`, `ERR_PILOT_TIME_CONFLICT`, `ERR_BOAT_TIME_CONFLICT`, `ERR_PERIOD_OVERLAP`), the invoice-finalize incident hold (`ERR_INCIDENT_HOLD_ACTIVE`), and the empty-pool fiscal check (`ERR_EMPTY_DISTRIBUTION_POOL`). Structural request validation — missing required fields, type mismatches, out-of-range enum values, quantities below their declared per-field minimum — is the final catch-all, surfacing `ERR_INVALID_REQUEST`. Two structural checks run earlier than that catch-all position, at the point a business rule consumes the value: a datetime field must parse as ISO 8601 before any temporal rule compares it against the clock; and a planned service window at dispatch or reassignment (`scheduled_start`/`scheduled_end`) or a distribution window (`period_start`/`period_end`) is validated — both instants parseable and the end strictly after the start — immediately after the state-machine guard (where one applies) and before any selector-pool, business-safety, overlap, or pool-emptiness check. Fields an endpoint does not consume — including client attempts to supply system-managed or computed fields such as `status`, `version`, `tariff_schedule_id`, or `provisional_fee_cents` — are ignored rather than rejected.

### 2.9. Rotation Board Invariants

The rotation board is the association's fairness mechanism, and the system maintains three invariants on it. First, every registered pilot has exactly one `RotationEntry`, created automatically at registration. Second, `position` values are unique across all entries; a newly registered pilot enters at the bottom of the board with `position` set to one greater than the current maximum, and a pilot selected at dispatch is demoted to the bottom the same way, with their prior slot recorded in `previous_position` so a later cancellation can restore it. Third, board membership and pilot standing are linked: a pilot whose `status` becomes `SUSPENDED` has their entry moved to `OFF_BOARD`, and only `IN_ROTATION` entries participate in dispatch selection.

### 2.10. Interval Semantics: Pilots versus Boats

Pilots and pilot boats both accumulate booked intervals from their assignments, but they follow deliberately different adjacency semantics. A pilot's committed intervals are **closed** intervals with no buffer: a new assignment touching an existing one at an endpoint — the new `scheduled_start` equal to an existing `scheduled_end` — is a conflict. A pilot boat's committed intervals are **half-open with a turnaround buffer**: the boat remains occupied for 45 minutes beyond each booking's end, and a new request whose start falls exactly at the buffered edge is allowed. These asymmetries reflect operational reality — a pilot cannot teleport between ships, but a boat crew can turn around in three quarters of an hour — and the dispatch and reassignment selectors apply the correct semantics per resource.

## 3. Business Logic & Workflows

### 3.1. Membership, Endorsements, and the Rotation Board

An `AssociationAdmin` registers a new pilot member by supplying the pilot's `full_name`, state-issued `license_number` — which must be unique across pilots, with a duplicate rejected by `ERR_INVALID_REQUEST` (HTTP 400) — and `share_units` — the cooperative revenue-distribution weight, an integer which must be at least 1. Registration creates the pilot in `ACTIVE` status with `rest_until` null (no rest obligation until the pilot's first completion) and `duty_minutes_rolling_7d` at zero, and automatically creates the pilot's `RotationEntry` in `IN_ROTATION` status at the bottom of the board: `position` is set to one greater than the current maximum across all entries, with `previous_position` null.

A pilot's legal authority over vessel size is expressed through **license endorsements**. The admin issues an endorsement by supplying the `endorsement_class` — one of `HARBOR`, `COASTAL`, or `UNLIMITED` — a `tonnage_cap_gt` giving the maximum vessel gross tonnage the endorsement covers (a positive integer), and an `expires_at` instant — any ISO 8601 instant is accepted, even one already in the past (the endorsement is then simply not current). An endorsement is current only while its `status` is `CURRENT` and its `expires_at` is strictly after the logical clock. Endorsements are per-class superseding: creating a new endorsement in the same class as an existing `CURRENT` endorsement for the same pilot flips the older one to `SUPERSEDED`, and this mutation increments the pilot's `version` by one. Because supersession changes which endorsement a reader believes is current, the issuance call participates in optimistic concurrency: the request must carry `expected_pilot_version` matching the pilot's current `version`, and a stale view is rejected with `ERR_STALE_VERSION` (HTTP 412) per §2.7.

The board itself is readable by any role. A pilot detail read returns the member's computed fatigue posture — `rest_until` and `duty_minutes_rolling_7d` — alongside their registration data. The reverse-reachability views let a caller list a single pilot's endorsements, or fetch a pilot's rotation entry (an array of at most one row, keyed by `pilot_id`), while the board-wide listing is ordered by `position` ascending and accepts an optional `status` filter. An out-of-range `status` value on the board listing is rejected with `ERR_INVALID_REQUEST` (HTTP 400); every other list endpoint treats filter values as exact matches, so an unrecognized value simply yields an empty page.

### 3.2. Vessel Order Intake and Amendment

A `VesselAgent` opens a movement order by providing the `vessel_name`, the vessel's gross tonnage `gt` (a positive integer), the `draft_dm` (draft in decimeters, also a positive integer), the `order_type` — `ARRIVAL`, `DEPARTURE`, or `SHIFT` — and the `eta`, the estimated time of arrival or startup. The ETA must be strictly after the logical clock at intake; an ETA equal to the current clock reading fails with `ERR_ETA_IN_PAST`. Intake captures the caller's `X-User-ID` as the order's `agent_id`, which later governs amendment and cancellation ownership.

Intake also pins a tariff schedule to the order: the schedule with the greatest `effective_from` at or before the logical clock — the schedule whose computed `status` is `ACTIVE` — is recorded as the order's `tariff_schedule_id`, and the provisional tariff is computed over the declared `gt` and `draft_dm` under the **average-rate** variant of the tariff (see §3.6) and stored as `provisional_fee_cents`. When no schedule is effective at intake, the order is still created, with `tariff_schedule_id` and `provisional_fee_cents` both null. The order is born in `BOOKED` status.

While the order remains `BOOKED`, the owning agent may amend it — updating `eta`, `gt`, or `draft_dm`. Amendment requires `expected_order_version` matching the order's current `version` per §2.7, and is rejected with `ERR_STALE_VERSION` (HTTP 412) when another writer has advanced the order since the client last read it. The amended ETA is again validated as strictly after the logical clock, with the same `ERR_ETA_IN_PAST` rejection. Once the order has left `BOOKED`, amendment is rejected with `ERR_ORDER_LOCKED` (HTTP 409). A successful amendment re-pins the tariff schedule (nulling `tariff_schedule_id` when no schedule is effective), recomputes `provisional_fee_cents` whenever `gt` or `draft_dm` was supplied, and increments the order's `version`.

Cancellation is symmetric to amendment in ownership: only the agent whose `X-User-ID` matches the order's `agent_id` may cancel, otherwise `ERR_FORBIDDEN`. Cancellation is legal only from `BOOKED` or `DISPATCHED`; from any other status it is rejected with `ERR_INVALID_STATE` (HTTP 409). Cancelling a `BOOKED` order simply moves it to `CANCELLED`. Cancelling a `DISPATCHED` order triggers a two-hop cascade: the order's non-terminal assignment moves to `CANCELLED` service status, and that assignment cancellation in turn restores the displaced pilot's board slot (`position` reverts to `previous_position`) and releases the boat's booked interval — with the board-slot restoration applying only when that assignment is still `ASSIGNED`, since a `RECALLED` assignment's turn was already consumed and its cancellation releases only the boat interval (§3.5). The order ends `CANCELLED`.

### 3.3. Dispatch: Selector-Gated Assignment Creation

A `Dispatcher` dispatches a `BOOKED` order by supplying the planned service window, `scheduled_start` and `scheduled_end`, with the end strictly after the start (the window is never compared against the logical clock, here or at reassignment, so a window in the past is accepted); an optional `boat_id` overrides boat selection — used as-is after the existence check, without any conflict check against the boat's committed intervals (contrast reassignment in §3.5) — and an optional `apprentice_id` attaches a training rider. Dispatch is only legal while the order is `BOOKED`; any other status is rejected with `ERR_ORDER_NOT_DISPATCHABLE` (HTTP 409). When an `apprentice_id` is supplied, it must reference an apprentice whose `status` is `ENROLLED` — dispatching against a `QUALIFIED` or `CERTIFIED` apprentice is rejected with `ERR_APPRENTICE_NOT_ENROLLED`.

Unless `boat_id` is given explicitly, the boat selector runs over the fleet: candidate boats are those with no conflicting committed interval under the half-open-plus-buffer semantics of §2.10, ranked by `created_at` ascending with ties broken by `name` ascending. An empty boat pool rejects the dispatch with `ERR_NO_ELIGIBLE_BOAT`.

Pilot selection is the rotation selector. The candidate pool is every pilot who is simultaneously: `ACTIVE`; `IN_ROTATION` on the board; holding at least one `CURRENT` endorsement with `expires_at` strictly after the logical clock and `tonnage_cap_gt` at least the order's `gt`; either never rested (`rest_until` null) or fully rested (`rest_until` at or before the clock); projected to remain within the seven-day duty ceiling after this assignment's planned minutes are added to their rolling duty total (equality passes; only a strictly-greater projection fails); and free of any closed-interval conflict against their committed assignments. The pool is ranked by board `position` ascending, ties broken by the entry's `created_at` ascending, and the top candidate is selected. An empty pool rejects the dispatch with `ERR_NO_ELIGIBLE_PILOT`, leaving the order `BOOKED` with no partial write. Boats are registered by the admin under a unique `name` (a duplicate is rejected with `ERR_INVALID_REQUEST`, HTTP 400) and a `capacity_persons` count (at least 1, covering crew plus passengers) — attributes that describe the vessel but do not enter the dispatch selector.

A successful dispatch creates the assignment with `service_status` `ASSIGNED` and `billing_status` `UNBILLED`, recording the selected or supplied `boat_id`, any `apprentice_id`, and the planned window, with `actual_start`, `actual_end`, `detention_minutes`, and `delay_minutes` null and `recall_count` zero. The order advances `BOOKED → DISPATCHED`. The selected pilot's rotation entry records the demotion: `previous_position` captures the current `position`, then `position` moves to one greater than the current board maximum.

### 3.4. In-Service: Launch, Boarding, Completion

The service half of an assignment's dual status is driven by the assigned pilot, and ownership is strict: only the pilot whose `X-User-ID` equals the assignment's `pilot_id` may act, otherwise `ERR_FORBIDDEN`.

Launching transitions the assignment `ASSIGNED → EN_ROUTE`, stamps `actual_start` from the logical clock, advances the order `DISPATCHED → IN_SERVICE` (refreshing the order's `updated_at`), and flips the boat from `AVAILABLE` to `ON_RUN`. Boarding then transitions `EN_ROUTE → ABOARD` with no further side effects. Attempting either step from the wrong state — completing directly from `ASSIGNED`, say — is rejected with `ERR_INVALID_STATE` (HTTP 409).

Completion is the system's richest single transaction. The pilot reports `detention_minutes` and `delay_minutes` — each required and non-negative — and the assignment transitions `ABOARD → COMPLETED`. The system stamps `actual_end` from the logical clock and computes the duty duration as the elapsed minutes between `actual_start` and `actual_end`, truncated down to whole minutes. The pilot's rest obligation is written next: when the duration reaches the long-duty threshold of 480 minutes (the boundary is inclusive — exactly 480 earns the long rest), `rest_until` is set 960 minutes beyond `actual_end`; shorter duties earn 600 minutes. Completion then mints the invoice: exactly one invoice per assignment, born in `ISSUED` status, carrying the **final marginal-rate** tariff as `base_fee_cents` plus the detention and delay extras (§3.6), and the assignment's billing dimension advances `UNBILLED → INVOICED` as part of the same write. The order completes (`IN_SERVICE → COMPLETED`, refreshing `updated_at`), the boat returns to `AVAILABLE`, and if an `apprentice_id` rides the assignment, that apprentice's `trips_completed` increases by one.

### 3.5. Cancellation, Recall, and Reassignment

Not every dispatched assignment sails. A `Dispatcher` can cancel an assignment directly, and the effect depends on the assignment's standing. Cancelling an `ASSIGNED` assignment restores the pilot's board slot as compensation for the dispatch demotion — `position` reverts to `previous_position` and `previous_position` is cleared to null — and releases the boat's booked interval. When the direct cancellation fires while the order is still `DISPATCHED`, the order reverts `DISPATCHED → BOOKED` so it can be dispatched again; by contrast, when the cancellation arrives as a cascade from the agent cancelling the order, the order proceeds to `CANCELLED` instead. Cancelling a `RECALLED` assignment simply releases the boat interval. The billing dimension of a cancelled assignment never advances: it remains `UNBILLED` forever.

Recall is the dispatcher's pre-launch pull: recalling an `ASSIGNED` assignment moves it to `RECALLED`, increments its `recall_count`, and releases the boat interval — but deliberately does not restore the recalled pilot's board position. The turn is consumed; the order stays `DISPATCHED` awaiting reassignment.

Reassignment returns a `RECALLED` assignment to `ASSIGNED`. The dispatcher may respecify any of `pilot_id`, `boat_id`, `scheduled_start`, and `scheduled_end`. When `pilot_id` is present in the payload, the explicit pilot runs a five-check validation path in pinned order: a `CURRENT` endorsement with `expires_at` strictly after the clock (`ERR_LICENSE_NOT_CURRENT`), an endorsement `tonnage_cap_gt` at least the order's `gt` (`ERR_TONNAGE_EXCEEDS_ENDORSEMENT`), a `rest_until` that is null or no later than the clock (`ERR_FATIGUE_REST_ACTIVE`), a rolling-duty-plus-new-minutes projection within the seven-day ceiling with equality passing (`ERR_FATIGUE_DUTY_LIMIT`), and a closed-interval overlap check against the pilot's committed assignments (`ERR_PILOT_TIME_CONFLICT`, HTTP 409). When `pilot_id` is absent, the rotation selector of §3.3 runs instead, with an empty pool again surfacing `ERR_NO_ELIGIBLE_PILOT`. When `boat_id` is present, the explicit boat runs the half-open-plus-buffer overlap check, conflicting with `ERR_BOAT_TIME_CONFLICT` (HTTP 409); when `boat_id` is absent, the assignment keeps its current boat, which is not re-checked even if the window moved. In both interval checks the assignment undergoing reassignment is excluded from its own conflict set. A successful reassignment applies the payload's pilot, boat, and window updates, and the newly assigned pilot's rotation entry records the same demotion as at dispatch — `previous_position` captures the current `position`, then `position` moves to one past the board maximum.

### 3.6. Tariff Schedules and the Two-Variant Fee Engine

Tariffs are published by an `AssociationAdmin` as effective-dated **tariff schedules**. Each schedule declares its `effective_from`; a non-empty `tiers` array whose members each carry `min_gt_exclusive` (an integer ≥ 0), `max_gt_inclusive` (null for the open-ended top tier, otherwise an integer strictly greater than `min_gt_exclusive`), and `rate_cents_per_gt` (an integer ≥ 0) — tier ordering and contiguity are not validated; the draft surcharge pair `draft_surcharge_threshold_dm` (a non-negative integer) and `draft_surcharge_pct` (a non-negative number, fractional values allowed); and the extras rates `detention_free_minutes`, `detention_rate_cents_per_minute`, and `delay_rate_cents_per_minute` (all non-negative integers). A schedule's `status` is computed, not stored: the schedule with the greatest `effective_from` at or before the logical clock is `ACTIVE` (ties on equal `effective_from` broken by `created_at` ascending); any schedule whose `effective_from` is strictly after the clock is `SCHEDULED`; and every remaining row — including a future-dated schedule that a newer, already-effective schedule leapfrogs — is `SUPERSEDED`. Clock advancement re-resolves these statuses automatically, and publishing a new schedule triggers the same re-resolution.

The tariff engine runs in two variants over the same pinned schedule. The **provisional average-rate** variant fires at order intake and on every amendment that changes `gt` or `draft_dm`: the single tier whose band contains the order's `gt` prices the entire tonnage at that tier's rate (if the `gt` falls outside every declared band, the last declared tier's rate is used), and the result is stored on the order as `provisional_fee_cents`. The **final marginal-rate** variant fires at assignment completion and becomes the invoice's `base_fee_cents`: each tier prices only the tonnage actually inside its band — for each tier, the chargeable tonnage is the smaller of the order's `gt` and the tier's upper bound, minus the tier's lower bound, floored at zero — and the per-tier products are summed. Both variants then apply the draft surcharge identically: when the order's `draft_dm` is strictly greater than the schedule's `draft_surcharge_threshold_dm`, the base is multiplied by one plus the `draft_surcharge_pct` and rounded half-up to integer cents — the only rounding step in the base computation.

The final invoice composition adds the two extras on top of the marginal base. The detention component, `detention_fee_cents`, charges for claimed detention beyond the schedule's free allowance: the greater of zero and (`detention_minutes` minus `detention_free_minutes`), multiplied by `detention_rate_cents_per_minute`. The delay component, `delay_fee_cents`, charges the full `delay_minutes` at `delay_rate_cents_per_minute` with no allowance. Per §2.6, each component is rounded half-up to integer cents first, and `total_cents` is the sum of the three rounded components. An order whose pinned `tariff_schedule_id` is null — no schedule was effective at intake or amendment — completes with all three components and `total_cents` at zero.

### 3.7. Fatigue Governance

Fatigue is governed by two complementary rules, both expressed in whole minutes and both evaluated against the logical clock.

The **rolling duty rule** maintains each pilot's `duty_minutes_rolling_7d`: the sum, over that pilot's own `COMPLETED` assignments whose `actual_end` falls at or after the instant seven days before now (the boundary is inclusive), of each assignment's elapsed duty minutes from `actual_start` to `actual_end`. Cancelled and recalled assignments and in-progress rows are excluded. For eligibility — in the rotation selector and in explicit reassign validation — the projected load adds the candidate assignment's planned minutes (`scheduled_end` minus `scheduled_start`) to the rolling total; the pilot is eligible when the projection is at most 4320 minutes, the association's seven-day ceiling. Equality passes; only a strictly-greater projection fails with `ERR_FATIGUE_DUTY_LIMIT` on the explicit path or excludes the pilot from the selector pool.

The **rest rule** is written at completion per §3.4 and read at eligibility: a pilot is available when `rest_until` is null or no later than the logical clock. An explicit reassign against a still-resting pilot is rejected with `ERR_FATIGUE_REST_ACTIVE`.

### 3.8. Invoicing, Incident Hold, and Revenue Distribution

Invoices are born `ISSUED` at completion. A `FinanceOfficer` finalizes an `ISSUED` invoice, stamping `finalized_at` from the logical clock — but only when no incident attached to the same assignment is still open. While any incident on the assignment sits in `REPORTED` or `UNDER_REVIEW`, finalization is rejected with `ERR_INCIDENT_HOLD_ACTIVE` (HTTP 422). Finalization is the gateway to distribution: only `FINALIZED` invoices with `finalized_at` inside a run's window join its pool.

Periodically the finance officer computes a **distribution run** over a half-open window: `period_start` inclusive, `period_end` exclusive, with the end strictly after the start. The window must not overlap any existing run in `COMPUTED` or `SETTLED` status — adjacency is allowed, so a new `period_start` equal to an existing run's `period_end` passes — otherwise `ERR_PERIOD_OVERLAP` (HTTP 409). The pool is every `FINALIZED` invoice whose `finalized_at` falls in the window; an empty pool rejects the run with `ERR_EMPTY_DISTRIBUTION_POOL`. The run's `gross_pool_cents` is the sum of the pool's `total_cents`. The association levy is then computed with a pinned anti-circular order: the levy percentage is keyed on the gross pool before any deduction — 0.10 when the gross reaches 10000000 cents, otherwise 0.08 — and `levy_cents` is the gross multiplied by that percentage, rounded half-up. The `net_pool_cents` is the gross minus the levy.

Distribution allocates the net pool across the distinct pilots behind the pooled invoices, weighted by each pilot's `share_units`. Each pilot's raw share is the net pool multiplied by their `share_units` and divided by the total units across eligible pilots; per §2.6 each share is rounded half-up to integer cents first, producing the `shares` array of `pilot_id`, `share_units`, and `share_cents` entries. The remainder — the net pool minus the sum of rounded shares — is reconciled one cent per pass: a positive remainder adds one cent per pass walking pilots by `created_at` ascending; a negative remainder removes one cent per pass walking pilots by `created_at` descending. The invariant after reconciliation is exact: the gross pool equals the levy plus the sum of all shares. The run records the swept invoice ids in `invoice_ids`, ordered by invoice `created_at` ascending, and the `shares` array is likewise ordered by pilot `created_at` ascending; the run is born in `COMPUTED` status.

Settling a `COMPUTED` run sweeps every invoice in `invoice_ids` from `FINALIZED` to `DISTRIBUTED` and advances each such invoice's assignment billing dimension `INVOICED → SETTLED`. Voiding a `COMPUTED` run instead moves the run to `VOID` with no invoice or assignment mutation — the swept invoices remain `FINALIZED`, releasing the run's reservation so a later window can pick them up.

### 3.9. Incident Investigation and the Suspension Cascade

An incident is reported against a specific assignment — by the assigned pilot (ownership: the pilot may report only their own assignments) or by a `Dispatcher` — supplying the `assignment_id`, an `incident_type` of `GROUNDING`, `COLLISION`, `NEAR_MISS`, `EQUIPMENT`, or `CONDUCT`, and a free-text `description`. The reported incident derives its `pilot_id` from the assignment's pilot and is born in `REPORTED` status. While any incident on an assignment remains `REPORTED` or `UNDER_REVIEW`, that assignment's invoice cannot be finalized (§3.8).

An `Investigator` drives the review. Opening the review moves `REPORTED → UNDER_REVIEW`. From there the case forks with deliberately divergent side effects. Dismissal moves `UNDER_REVIEW → DISMISSED` and touches nothing — the pilot, the rotation entry, and the pilot's assignments are all left exactly as they stand. Substantiation instead fires a three-hop cascade: the pilot's `status` moves `ACTIVE → SUSPENDED`; that suspension pushes the pilot's rotation entry to `OFF_BOARD`; and the board removal recalls every one of that pilot's assignments still in `ASSIGNED` — each moves to `RECALLED` with its `recall_count` incremented and its boat interval released, per the recall semantics of §3.5. A substantiated case is closed with a mandatory, non-empty `corrective_note`, moving `SUBSTANTIATED → CLOSED` and persisting the note. `DISMISSED` and `CLOSED` are terminal; acting on an incident from a state the transition does not allow — dismissing from `REPORTED`, closing from `UNDER_REVIEW` — is rejected with `ERR_INVALID_STATE`.

### 3.10. The Apprentice Program

An `AssociationAdmin` enrolls an apprentice with a `full_name` and a progression `track` of `STANDARD` or `ACCELERATED`; the apprentice starts `ENROLLED` with `trips_completed` and `evaluations_count` at zero and `evaluation_avg` at 0. Training credit accrues two ways: each completed riding assignment (§3.4) adds one trip, and the admin can log progress directly, supplying `trips_delta` to add to `trips_completed` and an `evaluation_score` to fold into the running average — neither is range-checked (`trips_delta` may be any integer, including a negative one, and `evaluation_score` may be any number), and progress may be logged at any status, including after certification. The running average updates per recorded score: the prior average times the prior count, plus the new score, divided by the new count, rounded half-up to two decimal places — then `evaluations_count` increments. When no scores have been recorded, `evaluation_avg` reads 0.

Advancement is a two-rung ladder with track-dependent readiness at the first rung. From `ENROLLED` to `QUALIFIED`, the readiness variant is selected by `track`: a `STANDARD` apprentice qualifies on trips alone, needing at least 50 completed trips; an `ACCELERATED` apprentice faces a blended bar — at least 40 trips and an `evaluation_avg` of at least 85 — so identical trip and evaluation data can yield opposite verdicts across tracks. Failing the variant rejects advancement with `ERR_READINESS_NOT_MET`. From `QUALIFIED` to `CERTIFIED`, the admin supplies `exam_result`, and only the value `PASS` advances the apprentice; anything else (or its absence) is rejected with `ERR_EXAM_NOT_PASSED`. `CERTIFIED` is terminal; attempting to advance from it is rejected with `ERR_INVALID_STATE` (HTTP 409).

## 4. Endpoint Definitions

Operations that create new resources (a pilot, an order, an endorsement, a boat, a tariff schedule, an apprentice, an incident, a distribution run, or the assignment minted by dispatch) return `201 Created`. Operations that modify an existing resource — state transitions, amendments, completions, finalization, settlement — return `200 OK`. Reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/pilotage/pilots` | Register a pilot member; auto-creates the rotation entry at the bottom of the board | AssociationAdmin |
| GET | `/pilotage/pilots/{id}` | Pilot detail including computed `rest_until` and `duty_minutes_rolling_7d` | Any |
| POST | `/pilotage/pilots/{id}/endorsements` | Issue an endorsement; same-class `CURRENT` endorsement becomes `SUPERSEDED`; OCC on the pilot's version | AssociationAdmin |
| GET | `/pilotage/pilots/{id}/endorsements` | List a pilot's endorsements | Any |
| GET | `/pilotage/pilots/{id}/rotation-entries` | The pilot's rotation entry (array of zero or one) | Any |
| GET | `/pilotage/rotation-entries` | Rotation board listing ordered by `position` ascending; optional `status` filter | Any |
| POST | `/pilotage/vessel-orders` | Order intake; pins the `ACTIVE` tariff schedule and computes the provisional fee | VesselAgent |
| GET | `/pilotage/vessel-orders` | List orders; optional `status` and `tariff_schedule_id` filters | Any |
| GET | `/pilotage/vessel-orders/{id}` | Order detail | Any |
| PATCH | `/pilotage/vessel-orders/{id}` | Amend ETA / tonnage / draft while `BOOKED`; OCC on the order's version; recomputes the provisional fee | VesselAgent |
| POST | `/pilotage/vessel-orders/{id}/cancel` | Agent cancels own `BOOKED` or `DISPATCHED` order; from `DISPATCHED` cascades assignment cancel, rotation compensation, and boat release | VesselAgent |
| POST | `/pilotage/vessel-orders/{id}/dispatch` | Dispatch the order: rotation selector picks the pilot; boat selector picks the boat unless `boat_id` given | Dispatcher |
| GET | `/pilotage/assignments` | List assignments; filters for `order_id`, `pilot_id`, `boat_id`, `apprentice_id`, `service_status`, `billing_status` | Any |
| GET | `/pilotage/assignments/{id}` | Assignment detail | Any |
| POST | `/pilotage/assignments/{id}/start` | Pilot (own) launches: `ASSIGNED → EN_ROUTE`; order to `IN_SERVICE`; boat to `ON_RUN` | Pilot |
| POST | `/pilotage/assignments/{id}/board` | Pilot (own) boards: `EN_ROUTE → ABOARD` | Pilot |
| POST | `/pilotage/assignments/{id}/complete` | Pilot (own) completes: mints the `ISSUED` invoice, writes rest, completes the order, frees the boat, credits the apprentice | Pilot |
| POST | `/pilotage/assignments/{id}/cancel` | Dispatcher cancels an `ASSIGNED`/`RECALLED` assignment; rotation position restored; order reverts to `BOOKED` when directly cancelled | Dispatcher |
| POST | `/pilotage/assignments/{id}/recall` | Dispatcher recalls an `ASSIGNED` assignment | Dispatcher |
| POST | `/pilotage/assignments/{id}/reassign` | Dispatcher reassigns a `RECALLED` assignment; explicit pilot/boat run the validation paths, absent pilot runs the selector | Dispatcher |
| POST | `/pilotage/pilot-boats` | Register a pilot boat | AssociationAdmin |
| GET | `/pilotage/pilot-boats` | List boats; optional `status` filter over the computed `AVAILABLE`/`ON_RUN` | Any |
| POST | `/pilotage/tariff-schedules` | Publish an effective-dated tariff schedule | AssociationAdmin |
| GET | `/pilotage/tariff-schedules` | List schedules with computed status; optional `status` filter | Any |
| GET | `/pilotage/invoices` | List invoices; optional `assignment_id` and `status` filters | Any |
| GET | `/pilotage/invoices/{id}` | Invoice detail | Any |
| POST | `/pilotage/invoices/{id}/finalize` | Finalize an `ISSUED` invoice; blocked by open incidents on the assignment | FinanceOfficer |
| POST | `/pilotage/incidents` | Report an incident on an assignment (pilot on own, or dispatcher) | Pilot, Dispatcher |
| GET | `/pilotage/incidents` | List incidents; optional `assignment_id`, `pilot_id`, `status` filters | Any |
| GET | `/pilotage/incidents/{id}` | Incident detail | Any |
| POST | `/pilotage/incidents/{id}/open-review` | `REPORTED → UNDER_REVIEW` | Investigator |
| POST | `/pilotage/incidents/{id}/dismiss` | `UNDER_REVIEW → DISMISSED` (terminal; no cascade) | Investigator |
| POST | `/pilotage/incidents/{id}/substantiate` | `UNDER_REVIEW → SUBSTANTIATED`; suspension cascade suspends the pilot, removes them from the board, recalls their `ASSIGNED` assignments | Investigator |
| POST | `/pilotage/incidents/{id}/close` | `SUBSTANTIATED → CLOSED` with mandatory `corrective_note` | Investigator |
| POST | `/pilotage/apprentices` | Enroll an apprentice | AssociationAdmin |
| GET | `/pilotage/apprentices` | List apprentices; optional `track` and `status` filters | Any |
| POST | `/pilotage/apprentices/{id}/record-progress` | Log training trips and an evaluation score | AssociationAdmin |
| POST | `/pilotage/apprentices/{id}/advance` | `ENROLLED → QUALIFIED` on track readiness; `QUALIFIED → CERTIFIED` on a passing exam | AssociationAdmin |
| POST | `/pilotage/distribution-runs` | Compute a distribution run over `FINALIZED` invoices in the window | FinanceOfficer |
| GET | `/pilotage/distribution-runs/{id}` | Run detail including the `shares` array | Any |
| POST | `/pilotage/distribution-runs/{id}/settle` | `COMPUTED → SETTLED`; swept invoices to `DISTRIBUTED`, assignment billing to `SETTLED` | FinanceOfficer |
| POST | `/pilotage/distribution-runs/{id}/void` | `COMPUTED → VOID`; invoices remain `FINALIZED` | FinanceOfficer |
| POST | `/pilotage/_clock/set_current_utc` | Set the logical clock (startup default `2026-08-01T00:00:00Z`; never falls back to wall-clock) | AssociationAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ORDER_LOCKED` | 409 |
| `ERR_ORDER_NOT_DISPATCHABLE` | 409 |
| `ERR_NO_ELIGIBLE_PILOT` | 422 |
| `ERR_NO_ELIGIBLE_BOAT` | 422 |
| `ERR_LICENSE_NOT_CURRENT` | 422 |
| `ERR_TONNAGE_EXCEEDS_ENDORSEMENT` | 422 |
| `ERR_FATIGUE_REST_ACTIVE` | 422 |
| `ERR_FATIGUE_DUTY_LIMIT` | 422 |
| `ERR_PILOT_TIME_CONFLICT` | 409 |
| `ERR_BOAT_TIME_CONFLICT` | 409 |
| `ERR_ETA_IN_PAST` | 422 |
| `ERR_INCIDENT_HOLD_ACTIVE` | 422 |
| `ERR_READINESS_NOT_MET` | 422 |
| `ERR_EXAM_NOT_PASSED` | 422 |
| `ERR_APPRENTICE_NOT_ENROLLED` | 422 |
| `ERR_EMPTY_DISTRIBUTION_POOL` | 422 |
| `ERR_PERIOD_OVERLAP` | 409 |
| `ERR_INTERNAL` | 500 |

# Ag Drone Remote Sensing API — Product Requirements Document

## 1. Introduction

Agricultural producers increasingly buy aerial intelligence the way they buy seed and chemicals: as a seasonal service with acreage-based pricing, not as capital equipment. This document specifies the API for an agricultural drone and remote-sensing service operator — a platform through which growers subscribe to imagery scouting and, where licensed, spray-dispensing missions flown over their fields. The service covers the full operating loop: flight planning under FAA airspace rules, capture windows constrained by observed weather, processing of raw imagery into NDVI and plant-count deliverables, agronomist review of the scouting alerts those deliverables raise, per-acre subscription billing with tiered overage, pesticide application record-keeping, and an insurance and liability workflow for missions that go wrong.

Two forces shape every rule in this document. The first is regulatory: remote pilots fly under Part 107 certificates, controlled airspace demands LAANC authorization with hard altitude and time-window boundaries, and spray operations carry state applicator licensing plus immutable application records. The second is commercial: billing is subscription-based with included acreage and volume-discounted overage, deliverable access is time-boxed by plan, and claim payouts flow back into a grower's prepaid credit ledger. All resources are served under the `/ag-drone` mount. Because flight operations, authorization validity, and data retention all turn on the passage of time, the platform runs on a logical clock that administrators can advance explicitly, and several lifecycle transitions are driven by that clock rather than by client requests.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. A request in which either header is missing or empty is rejected with `ERR_MISSING_AUTH_CONTEXT` (HTTP 401). Once authenticated, the declared role must appear in the endpoint's authorized-role list; a role attempting an operation outside its grant is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Seven roles are recognized, spelled exactly as follows: `OpsAdmin`, `FlightCoordinator`, `RemotePilot`, `Agronomist`, `Grower`, `ClaimsAdjuster`, and `ProcessingEngine`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `RemotePilot`, `X-User-ID` is the `id` of the acting `PilotProfile`; ownership checks on any resource that references a `PilotProfile` compare the resource's foreign-key field to `X-User-ID` — most importantly, in-flight operations compare the mission's `pilot_id` to it. When `X-User-Role` is `Agronomist`, `X-User-ID` is likewise the `id` of the acting `PilotProfile` (agronomists are credentialed pilots performing review duty), and review-related ownership checks compare an alert's `reviewing_agronomist_id` or the originating mission's `pilot_id` to it. When `X-User-Role` is `Grower`, `X-User-ID` is the `id` of the acting `Grower`; ownership checks on any resource that references a `Grower` — directly or through a field, mission, deliverable, or claim beneath it — compare the resource's grower reference to `X-User-ID`, so a grower sees and acts on only their own account. When `X-User-Role` is `OpsAdmin`, `FlightCoordinator`, `ClaimsAdjuster`, or `ProcessingEngine`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `adjuster_user_id` on an `InsuranceClaim` when a claim review is opened) but does not compare it to any entity's `id`.

Segregation of duties is a first-class principle in this role model. The pilot who flew a mission is forbidden from reviewing scouting alerts raised from that mission's deliverables, and the state pesticide applicator license is a distinct credential from the FAA Part 107 remote pilot certificate — holding one never implies holding the other.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter states how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Primary resources — subscription plans, growers, fields, pilot profiles, flight missions, imagery deliverables, scouting alerts, and insurance claims — share a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource, including mutations caused by cascading side effects from operations on other resources.

Two resources are deliberately leaner. An `AirspaceAuthorization` and a `SprayMissionRecord` each carry only `id` and `created_at`; both `updated_at` and `version` are absent from them. The spray record is immutable by regulation, and the authorization's lifecycle is driven by explicit revocation or clock expiry rather than by optimistic-concurrency clients.

### 2.5. The Logical Clock and Scheduled Time Sweeps

Time in this platform is logical, not wall-clock. At startup the server's logical clock reads exactly `2026-08-01T00:00:00Z`, and until an administrator explicitly sets it, every time-dependent rule in the system evaluates against that default — the server never falls back to wall-clock time. An admin-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and responds with the resulting `current_utc`.

Advancing the clock triggers two automatic sweeps. First, any `AirspaceAuthorization` still `ACTIVE` whose `effective_until` has been reached — that is, the current time is at or past the authorization's end instant — transitions to `EXPIRED`; as a cascade, every `AUTHORIZED` mission referencing that authorization whose `scheduled_start` is at or after the current time is moved to `CANCELLED`. Second, any `ImageryDeliverable` in `READY` or `DELIVERED` whose `accessible_until` has been reached transitions to `EXPIRED`, after which grower reads of that deliverable are refused.

### 2.6. Nested Resource Retrieval and the Validation Pipeline

Requests that target nested resources are validated left to right along the path. Each path identifier, and then each foreign key in the request body, must resolve to an existing entity — grower first, then field, then mission, and so on down the hierarchy — and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that fails to resolve, before later identifiers are even examined.

More generally, every request passes through a fixed validation pipeline, and the order is part of the contract. First, the authentication context (headers present and non-empty, else `ERR_MISSING_AUTH_CONTEXT`). Second, role authorization (else `ERR_FORBIDDEN_ROLE`). Third, existence of every path and body reference, left to right (else `ERR_NOT_FOUND`). Fourth, state-machine preconditions on the target entity (a 409 rejection carrying the transition's specific state error, or the generic `ERR_INVALID_STATE` where no more specific code applies). Only after all four of those gates come the business rules, in their own fixed priority sequence: pilot certificate and applicator-license currency (`ERR_PILOT_CERT_EXPIRED`), then airspace authorization sufficiency (`ERR_AUTH_WINDOW_INSUFFICIENT`, or `ERR_AUTH_NOT_PERMITTED` where an authorization was supplied for non-controlled airspace), then spray-plan entitlement (`ERR_SPRAY_PLAN_FORBIDDEN`), then observed-weather limits (`ERR_WEATHER_LIMIT_EXCEEDED` / `ERR_WEATHER_LIMIT_NOT_EXCEEDED`), then the same-field scheduling-conflict scan (`ERR_MISSION_WINDOW_CONFLICT`), then segregation-of-duties and actor-identity checks (`ERR_SELF_REVIEW_FORBIDDEN`, `ERR_NOT_CLAIMING_AGRONOMIST`, `ERR_NOT_ASSIGNED_PILOT`), then temporal window checks (`ERR_OUTSIDE_WINDOW`), then deliverable access expiry (`ERR_DELIV_EXPIRED`), and finally the fiscal limits (`ERR_CLAIM_EXCEEDS_COVERAGE`, `ERR_CLAIM_NOT_APPROVED`). Because the pipeline is ordered, an earlier failure masks later ones: a request that fails authentication never reports a scheduling conflict.

Separately from this pipeline, malformed input on any endpoint — a required field missing, a value of the wrong type, an enum outside its declared range, or a violated domain input invariant such as planned acreage above the field's deeded acreage, a mission window whose end does not follow its start, a window longer than six hours, a non-positive claim amount, or a liability coverage purchase below the floor — is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.7. Precision, Rounding, and Units

All money in the platform is integer cents: base fees, overage rates, claim amounts, approved payouts, invoice totals, liability caps, and the grower's credit ledger are whole numbers of cents with no fractional part. Where a per-line monetary amount must be rounded, it is rounded half-up to a whole cent, and — critically for billing — every line is rounded before lines are summed, so the rounding of a multi-mission invoice is pinned to the individual mission lines and never re-derived from an aggregate.

Vegetation-index values carry three decimal places: a mean NDVI is reported to exactly three decimals, and the stress threshold is expressed to the same precision. Anomaly counts, acreage figures, plant counts, wind readings, and health scores are integers. Temporal-window comparisons (authorization containment, scheduling conflicts, launch windows) are evaluated on ISO 8601 UTC instants at seconds precision. A field's health score is an integer that can never fall below 0 nor rise above 100, regardless of what the underlying computation yields.

### 2.8. Optimistic Concurrency Control

Exactly two write operations participate in optimistic concurrency control, each keyed to a parent entity's `version`.

Replanning a disrupted mission requires the request to carry `expected_mission_version`, holding the `version` of the original `FlightMission` as the client last observed it. If that value does not match the mission's current `version` — because another writer has already replanned or otherwise advanced the mission since the client read it — the request is rejected with `ERR_STALE_MISSION_VERSION` (HTTP 412). This prevents a client from spawning a replacement revision on top of a mission state it has not observed.

Updating a grower's subscription plan or liability coverage requires the request to carry `expected_grower_version`, matching the grower's current `version`. A suspension, reinstatement, invoice run, or claim payout all advance the grower's version, so a client patching against a stale read — whose assumptions about year-to-date acreage or account standing no longer hold — is rejected with `ERR_STALE_GROWER_VERSION` (HTTP 412).

No other endpoint takes a version field; clients must not supply one elsewhere.

### 2.9. Hierarchical Consistency and Cascading State Changes

The resource tree runs grower to field to mission, with deliverables and spray records beneath missions, alerts anchored to fields, and claims anchored to growers. When a parent becomes non-operational, dependent work beneath it is resolved in the same transaction rather than left dangling: suspending or terminating a grower cancels that grower's not-yet-flown missions, revoking an airspace authorization cancels the missions that relied on it, and clock-driven expiry of an authorization cancels future authorized flights under it. Conversely, events at the leaf level propagate upward — a completed mission rewrites its field's surveyed acreage and the grower's year-to-date billable acreage, and a paid claim flows into the grower's credit balance. Every such cascade is a real mutation on the affected resource: its `updated_at` refreshes and its `version` increments, which is precisely what the optimistic-concurrency checks in §2.8 key on.

### 2.10. Airspace Governance and Authorization Windows

Every field is classified by FAA airspace class — one of `G`, `E`, `D`, `C`, or `B` — and the platform derives from that whether LAANC authorization is required: classes `B`, `C`, and `D` are controlled airspace and require an authorization, while classes `G` and `E` do not. An authorization is registered with a reference number from LAANC or DroneZone, an approved ceiling that may not exceed 400 feet above ground level, and a validity window from `effective_from` (inclusive) to `effective_until` (exclusive).

Window containment has exact boundary semantics. An authorization covers a mission window only when the authorization's start is at or before the mission's planned takeoff — an authorization that becomes effective at the exact takeoff instant is valid — and the mission's planned landing falls strictly before the authorization's end instant; a landing scheduled at the exact expiry instant is rejected. Adjacency is not sufficiency: two authorizations whose windows merely abut do not merge, and a mission straddling their seam cannot be flown under either.

### 2.11. Flight Separation and the Scheduling Buffer

No two live missions may crowd the same field. Each mission occupies a buffered window: its planned interval padded by 30 minutes on each side, treated as a half-open interval that includes its padded start and excludes its padded end. Two missions on the same field conflict when both are non-terminal — anything other than `COMPLETED`, `CANCELLED`, or `WEATHER_ABORTED` — and their buffered windows intersect. Missions whose buffered windows are exactly back-to-back, where one mission's padded end equals the other's padded start with zero gap, are permitted. The conflict scan runs when a mission is authorized and again whenever a mission is replanned into a new window; a detected conflict is rejected with `ERR_MISSION_WINDOW_CONFLICT` (HTTP 409).

## 3. Business Logic & Workflows

### 3.1. Commercial Onboarding: Plans, Growers, Fields, and Pilots

Everything commercial starts with the catalog. An `OpsAdmin` authors a subscription plan by supplying a unique `plan_code` (marketed codes resemble `SCOUT_BASIC`, `SCOUT_PRO`, or `SPRAY_FULL`), the `included_acres_per_year` that the base fee buys before overage applies, the annual `base_fee_cents`, the `overage_rate_cents_per_acre` charged beyond the allowance, a `spray_allowed` flag governing whether the plan entitles the grower to dispensing missions, the `ndvi_turnaround_hours` service-level target measured from mission completion to deliverable readiness, and the `storage_retention_days` for which processed deliverables remain accessible. Plans can be listed or read back by operations staff and by growers weighing their tier, and both list and detail views of the plan catalog are available to coordinators as well.

With a plan in place, an `OpsAdmin` registers a grower with the business `legal_name`, a `contact_email`, the chosen `subscription_plan_id`, the `subscription_started_on` date (an ISO calendar date in year-month-day form) on which the current subscription became effective, and the `liability_coverage_cents` the grower purchases as a per-occurrence cap. That coverage must be at least 50,000,000 cents; anything lower fails as `ERR_INVALID_REQUEST`. A freshly registered grower starts `ACTIVE` with `acres_included_ytd` at zero and `credit_balance_cents` at zero. The year-to-date acreage accumulates billable acres flown during the current subscription year and resets on each renewal anniversary; the credit balance is a prepaid ledger, debited by overage invoices and credited by insurance claim payouts. The grower roster can be listed with optional `status` or `subscription_plan_id` filters. An `OpsAdmin` may later patch a grower's `subscription_plan_id` or `liability_coverage_cents`, but only under the optimistic-concurrency contract of §2.8, carrying `expected_grower_version`.

Fields sit beneath growers. Either an `OpsAdmin` or the owning `Grower` creates a field under the grower's record with a grower-facing `field_name`, the authoritative deeded `legal_acres` (which must be a positive integer, or the request fails as `ERR_INVALID_REQUEST`), the FAA `airspace_class`, and the grower's aviation `insurance_policy_no` covering that field. On creation the platform derives `laanc_required` from the airspace class per §2.10, seeds `surveyed_acres` from the deeded acreage until a completed flight provides a measured figure, and initializes `health_score` to 100. A field carries no lifecycle status of its own; its derived health score is the dimension that moves. The system records the owning grower on the field as `grower_id`, and a grower's fields can be listed under their record.

The pilot registry is the last onboarding leg. An `OpsAdmin` registers each remote pilot with their `pilot_name`, the FAA `part107_certificate_no` (which must be unique across the registry), and the `part107_expires_on` currency date. Pilots who also dispense chemicals carry a state pesticide `applicator_license_no` with its `applicator_license_expires_on`; for pilots without one both default to the empty string, and the expiry stays empty whenever the license number is empty. A `night_waiver` flag, defaulting to false, records whether the pilot holds a Part 107.29 night-operations waiver. New pilots enter as `ACTIVE` and may later be marked `SUSPENDED`. The registry can be listed with an optional `status` filter.

### 3.2. Airspace Authorizations: Issuance, Revocation, and Expiry

Before any mission can be authorized over controlled airspace, an `OpsAdmin` or `FlightCoordinator` registers an airspace authorization against the target `field_id`, providing the FAA `authorization_ref`, the approved `max_altitude_ft` ceiling (at most 400 feet above ground level, else `ERR_INVALID_REQUEST`), and the validity window `effective_from` to `effective_until`. The authorization is born `ACTIVE` and, per §2.4, carries no `updated_at` or `version`. Authorizations can be listed with `field_id` or `status` filters, and read individually by operations staff, coordinators, and pilots checking their flight legality.

An authorization leaves `ACTIVE` in exactly two ways. An `OpsAdmin` may revoke it — permitted only while it is `ACTIVE`, else `ERR_AUTH_NOT_ACTIVE` — moving it to `REVOKED` and, in the same stroke, cancelling every `PLANNED` or `AUTHORIZED` mission that references it. Alternatively the clock sweep of §2.5 moves it to `EXPIRED` once its end instant is reached, cancelling those `AUTHORIZED` missions under it whose planned takeoff has not yet occurred. Both terminal states permanently disqualify the authorization from covering missions; a launch attempted against an authorization that is no longer `ACTIVE` fails with `ERR_AUTH_NOT_ACTIVE`.

### 3.3. Mission Planning, Authorization, and Replanning After Disruption

A `FlightCoordinator` plans a mission on a field by supplying the `mission_type` — `SCOUT` for pure imagery or `SPRAY` for dispensing — the assigned `pilot_id`, the planned `scheduled_start` and `scheduled_end` takeoff and landing instants, and the `acres_planned` coverage. The planned start must lie in the future at creation time, or the request is refused with `ERR_OUTSIDE_WINDOW`; the window itself must end after it starts and span no more than six hours, and the planned acreage must not exceed the field's deeded acreage, with either violation rejected as `ERR_INVALID_REQUEST`. For fields in controlled airspace the coordinator nominates an `authorization_id`, which otherwise defaults to null and must stay null. A `chemical_product_label` — the EPA-registered label — may be supplied and defaults to empty; it becomes mandatory at authorization time for spray work. `wind_kt_max_observed` and `gallons_dispensed` both default to zero at planning. A new mission is born `PLANNED` with `acres_flown` at zero. Missions on a field can be listed with an optional `status` filter, and a cross-field operations list can be narrowed by `status`, `field_id`, `pilot_id`, or `authorization_id`.

Authorization is the platform's densest gate, and its checks run in a fixed order. State preconditions come first: the mission must be `PLANNED` (else `ERR_MISSION_NOT_PLANNED`) and the owning grower must be `ACTIVE` (else `ERR_GROWER_NOT_ACTIVE`). Next come pilot credentials: the assigned pilot must be `ACTIVE` with a Part 107 certificate whose `part107_expires_on` falls on or after the scheduled landing date; for a `SPRAY` mission the pilot must additionally hold a non-empty applicator license whose `applicator_license_expires_on` also reaches the landing date, and the `chemical_product_label` must be non-empty — any failure here is `ERR_PILOT_CERT_EXPIRED`. The airspace check follows: when the field requires LAANC, the nominated authorization must be present, still `ACTIVE`, and its window must fully contain the mission window under the boundary semantics of §2.10, failing as `ERR_AUTH_WINDOW_INSUFFICIENT`; when the field does not require LAANC, any supplied `authorization_id` is itself a violation, `ERR_AUTH_NOT_PERMITTED`. Then plan entitlement: a `SPRAY` mission under a plan whose `spray_allowed` is false dies as `ERR_SPRAY_PLAN_FORBIDDEN`. Finally the scheduling scan of §2.11 runs, rejecting overlaps with `ERR_MISSION_WINDOW_CONFLICT`. A mission that survives every check transitions from `PLANNED` to `AUTHORIZED`, and its `version` increments.

Cancellation is the coordinator's release valve: a mission in `PLANNED` or `AUTHORIZED` may be cancelled into `CANCELLED` with a version increment, while a mission in any other state refuses with `ERR_MISSION_NOT_CANCELLABLE`.

When weather or circumstance kills a mission, the coordinator replans rather than edits. Replanning a `WEATHER_ABORTED` or `CANCELLED` mission spawns a brand-new mission — a fresh resource, not a mutation — carrying over the original's `field_id`, `mission_type`, `pilot_id`, `authorization_id`, `acres_planned`, and `chemical_product_label`, born `PLANNED` with the newly supplied `scheduled_start` and `scheduled_end`. The new start must again lie in the future (`ERR_OUTSIDE_WINDOW`), the window-shape invariants apply as at creation, and the same-field conflict scan of §2.11 runs against the new window. The request must also carry `expected_mission_version` under the optimistic-concurrency contract of §2.8; a mismatch with the original mission's current `version` is rejected as `ERR_STALE_MISSION_VERSION` (HTTP 412). On success the original mission's `version` increments, marking it superseded.

### 3.4. Flight Execution: Launch, Capture, and Weather Aborts

Flight operations belong to the assigned `RemotePilot` and to no one else: launching, capturing, or aborting a mission all require the caller's identity to equal the mission's assigned `pilot_id`, and any other pilot — or any other role — is refused with `ERR_NOT_ASSIGNED_PILOT` (HTTP 403).

Launching moves an `AUTHORIZED` mission to `IN_FLIGHT`. The mission must actually be `AUTHORIZED` (else `ERR_MISSION_NOT_AUTHORIZED`), the current time must fall within the planned window — at or after the planned takeoff and strictly before the planned landing — or the attempt is `ERR_OUTSIDE_WINDOW`, and where an authorization was nominated it must still be `ACTIVE` at launch, else `ERR_AUTH_NOT_ACTIVE`. A clean launch increments the mission's `version`.

Once airborne, the pilot either captures or aborts, and the deciding factor is the observed wind, measured in knots. Capturing records the flight's results — `acres_flown`, `wind_kt_max_observed`, and, for spray work, `gallons_dispensed` — and moves the mission from `IN_FLIGHT` to `CAPTURED`. Capture demands a mission genuinely in flight (else `ERR_MISSION_NOT_IN_FLIGHT`), a peak observed wind of at most 20 knots (anything stronger is rejected as `ERR_WEATHER_LIMIT_EXCEEDED`), and a flown acreage greater than zero and no more than the planned acreage (violations are `ERR_ACRES_OUT_OF_RANGE`). The three reported readings are stored on the mission and its `version` increments.

A weather abort is the mirror path, also from `IN_FLIGHT` (else `ERR_MISSION_NOT_IN_FLIGHT`): it is legitimate only when the peak observed wind exceeds 20 knots, and an abort attempted in calmer conditions is refused as `ERR_WEATHER_LIMIT_NOT_EXCEEDED`. An aborted mission lands in `WEATHER_ABORTED` with the observed wind recorded, `acres_flown` remaining zero, and the version incremented. Weather-aborted missions are exactly the kind of disruption §3.3's replanning exists for.

### 3.5. Mission Completion: Billing, Deliverables, and Spray Compliance Records

Completion is a `FlightCoordinator` act on a `CAPTURED` mission (anything else fails as `ERR_MISSION_NOT_CAPTURED`), and its payload names the processing products to produce via `deliverable_kinds` — each entry, `NDVI` or `PLANT_COUNT`, spawns one imagery deliverable in `PROCESSING` beneath the mission. Completion is the platform's busiest cascade. The mission moves to `COMPLETED`; the field's `surveyed_acres` is rewritten with the mission's actual `acres_flown`; the grower's `acres_included_ytd` grows by those same acres; and the versions of the mission, the field, and the grower all increment together.

When the completed mission was a spray operation, completion additionally writes a `SprayMissionRecord` — one record, one-to-one with the mission — snapshotting the pilot's `applicator_license_no`, the `chemical_product_label` applied, and the `gallons_dispensed` at completion time, and recording the label's `restricted_entry_interval_hours`, the number of hours during which re-entry to the field is forbidden, measured from the completion instant. Pesticide compliance makes this record immutable: `record_locked` is always true, the record carries no `updated_at` or `version`, and it is retrievable as an array holding zero or one entry depending on whether the mission dispensed.

Billing is computed at the moment of completion, in two variants that share one tier structure. Both start from the grower's year-to-date billable acreage as it stood immediately before this mission's acres were added, measured within the current subscription year — from `subscription_started_on` inclusive to the next anniversary exclusive. The included portion of the mission is the smaller of the acres flown and the allowance still remaining under the plan's `included_acres_per_year`, floored at zero when the allowance is already exhausted; whatever acres remain beyond that portion are overage. The `PROVISIONAL` variant, quoted to the grower immediately at completion, prices all overage acres at the plan's straight `overage_rate_cents_per_acre`. The `FINAL` variant, settled at the monthly invoice run, prices only the first 200 overage acres of a mission at the full overage rate; every overage acre beyond 200 is billed at a discounted per-acre rate equal to the overage rate multiplied by 0.80, that discounted rate itself rounded half-up to a whole cent. Under both variants each mission line is rounded half-up to integer cents before any summation across lines, so the sum of `FINAL` line amounts for an identical mission set can legitimately differ from the sum of `PROVISIONAL` amounts.

The monthly invoice run, invoked by an `OpsAdmin` against a grower with a `period_start` and `period_end`, computes `FINAL` billing across every one of the grower's `COMPLETED` missions in the period. The response breaks the run down into `line_items`, the settled `invoice_cents`, and the `provisional_total_cents` for the same set so the drift between estimate and settlement is visible. Settlement debits the grower's `credit_balance_cents` by the invoice amount — there is no floor check, and the balance is permitted to go negative — and advances the grower's `version` by one.

### 3.6. Imagery Processing, Anomaly Scoring, and Field Health

Processing is machine work. The `ProcessingEngine` submits its outputs for a deliverable that is still `PROCESSING` (a deliverable in any other state refuses with `ERR_DELIV_NOT_PROCESSING`), and the payload it must supply depends on the deliverable's `kind`. For an `NDVI` deliverable the payload's `ndvi_mean` is required and must lie between 0.000 and 1.000 inclusive, expressed to three decimal places; for a `PLANT_COUNT` deliverable the payload's `plant_count_per_acre` is required and must be greater than zero. Inputs that fail their kind's shape are rejected as `ERR_DELIV_INPUT_INVALID`. The payload may also carry `cells_below_threshold`, the engine's own census of stressed raster cells. A successful submission moves the deliverable to `READY`, records the processed bundle's object-store location as `storage_uri`, and stamps `accessible_until` as that instant plus the grower's plan `storage_retention_days` — the retention clock starts at readiness, not at delivery.

Anomaly scoring runs inside the same transition, deriving the deliverable's `anomaly_count`. For an `NDVI` deliverable, cells whose index value falls below 0.400 count as stressed — the payload reports their number directly — and the `anomaly_count` is that cell count multiplied by the mission's `acres_flown` and divided by one thousand, rounded half-up to a whole number. For a `PLANT_COUNT` deliverable the rule is binary: when the reported stand meets or exceeds 20,000 plants per acre the `anomaly_count` is zero, and otherwise every flown acre is anomalous, so the count equals `acres_flown`. Severity ladders off the result with inclusive boundaries: zero anomalies raise no alert at all; a count from 1 up through 9 raises a `LOW` alert; 10 up through 49 raises `MEDIUM`; and 50 or more raises `HIGH`. Whenever the count is positive, a `ScoutingAlert` is created against the field, referencing the `deliverable_id` that raised it, carrying the derived `severity`, born `OPEN` with `reviewing_agronomist_id` null, `review_notes` empty, and `review_outcome` unset.

Every readiness event also recomputes the field's `health_score`, as does any alert review concluding `DISMISSED` or `NEEDS_REFLIGHT`. The base comes from the field's most recently created deliverable that is `READY` or `DELIVERED`: for an `NDVI` product the base is the mean index multiplied by 100 and rounded to a whole number; for a `PLANT_COUNT` product it is the reported stand divided by the 30,000-plants-per-acre target, multiplied by 100, rounded to a whole number, and capped at 100. Against that base the platform subtracts a penalty summed over the field's `OPEN` and `UNDER_REVIEW` alerts, weighted 2 for `LOW`, 5 for `MEDIUM`, and 12 for `HIGH`; an alert that has just returned from review with a `NEEDS_REFLIGHT` outcome counts at double weight on the next recomputation, while dismissed alerts contribute nothing. The final score is the base minus the penalty, floored at 0 and capped at 100.

A `READY` deliverable is handed to the grower when a `FlightCoordinator` marks it delivered — possible only from `READY`, else `ERR_DELIV_NOT_READY` — moving it to `DELIVERED`. Access then remains time-boxed: once the logical clock reaches `accessible_until`, or once the sweep has moved the deliverable to `EXPIRED`, a grower's read of it is refused with `ERR_DELIV_EXPIRED` (HTTP 410). Deliverables for a mission can be listed, and individual deliverables read, by operations staff, coordinators, the owning grower, agronomists, and the processing engine.

### 3.7. Scouting Alerts and the Agronomist Review Workflow

An alert is work to be claimed. An `Agronomist` claims an `OPEN` alert — anything else is `ERR_ALERT_NOT_OPEN` — but segregation of duties bars the pilot who flew the originating mission from reviewing its own output: when the claimant's identity equals that mission's `pilot_id`, the claim is rejected with `ERR_SELF_REVIEW_FORBIDDEN` (HTTP 422). A successful claim moves the alert to `UNDER_REVIEW` and stamps `reviewing_agronomist_id` with the claimant's identity.

From `UNDER_REVIEW`, only the claiming agronomist may act; a review or release attempted by anyone whose identity differs from `reviewing_agronomist_id` is refused with `ERR_NOT_CLAIMING_AGRONOMIST` (HTTP 403), and an alert not actually under review refuses both actions with `ERR_ALERT_NOT_UNDER_REVIEW`. The review itself submits a `review_outcome` — which must be exactly one of `CONFIRMED`, `DISMISSED`, or `NEEDS_REFLIGHT`, anything else drawing `ERR_REVIEW_OUTCOME_INVALID` — optionally accompanied by `review_notes`, and moves the alert to its terminal `REVIEWED` state. The outcome steers the field's health: a `DISMISSED` alert is excluded from the health recomputation it triggers; a `NEEDS_REFLIGHT` outcome triggers the recomputation with that alert's severity weight doubled, and notably does not auto-create any replacement mission — replanning remains a human, coordinator-driven decision; a `CONFIRMED` alert simply closes the review with the anomaly standing as scored. Release is the gentler exit: the claiming agronomist hands the alert back to the queue, returning it to `OPEN` and clearing `reviewing_agronomist_id` to null.

Alert work queues are browsable two ways — per field, or across fields with `status`, `field_id`, `deliverable_id`, or `reviewing_agronomist_id` filters — so coordinators can watch a region while agronomists watch their own caseload.

### 3.8. Account Standing, Insurance Claims, and the Grower Credit Ledger

Account standing is an `OpsAdmin` lever with immediate operational teeth. Suspending a grower requires the grower to be `ACTIVE` (else `ERR_GROWER_NOT_ACTIVE`); the grower drops to `SUSPENDED`, every `PLANNED` or `AUTHORIZED` mission on that grower's fields is cancelled in the same transaction, and the grower's `version` increments. Reinstatement reverses the standing — only from `SUSPENDED`, else `ERR_GROWER_NOT_SUSPENDED` — returning the grower to `ACTIVE` with a version increment; missions already cancelled stay cancelled. Termination is final and also requires `SUSPENDED` (else `ERR_GROWER_NOT_SUSPENDED`), with one additional hard gate: no mission on any of the grower's fields may currently be `IN_FLIGHT`, or the termination is blocked with `ERR_MISSION_IN_FLIGHT`. A terminated grower's remaining `PLANNED` or `AUTHORIZED` missions are cancelled, and every non-terminal insurance claim on the account is denied outright with its `approved_amount_cents` zeroed. `TERMINATED` is terminal.

Claims begin with the grower. A `Grower` submits a claim against their own record, naming the `mission_id` on which the loss occurred and the `claim_amount_cents` sought — a positive integer, or the submission fails as `ERR_INVALID_REQUEST`. The claim is born `SUBMITTED` with `approved_amount_cents` at zero. A `ClaimsAdjuster` then opens review — only on a `SUBMITTED` claim, else `ERR_CLAIM_NOT_SUBMITTED` — moving it to `UNDER_REVIEW` and recording their own opaque operator id as `adjuster_user_id` for audit.

Adjudication has three exits. Approval, from `UNDER_REVIEW` (else `ERR_CLAIM_NOT_UNDER_REVIEW`), requires the referenced mission to be final — `COMPLETED` or `WEATHER_ABORTED`, anything earlier drawing `ERR_CLAIM_MISSION_NOT_FINAL` — and takes an `amount_cents` that must be positive and, added to the running total of already approved or paid amounts across all claims on the same mission, must not exceed the grower's `liability_coverage_cents`; a request that breaches the cap is `ERR_CLAIM_EXCEEDS_COVERAGE`. Approval records the payload amount as `approved_amount_cents`. Denial, likewise from `UNDER_REVIEW`, moves the claim to `DENIED` with `approved_amount_cents` zeroed. Payment is the payout: an `APPROVED` claim — anything else is `ERR_CLAIM_NOT_APPROVED` — moves to `PAID`, the grower's `credit_balance_cents` is credited by the approved amount, and the grower's `version` increments. Claims are browsable per grower or, for adjusters and operations staff, across the book with `status`, `mission_id`, or `grower_id` filters. Spray records for implicated missions are visible to adjusters, keeping the compliance trail one read away from the claim file.

## 4. Endpoint Definitions

Operations that create a new resource — registering a plan, grower, field, pilot, or authorization; planning a mission; submitting a claim; or replanning a mission into a fresh revision — return `201 Created`. Reads, state-transition actions, patches, and invoice runs that modify an existing resource return `200 OK`. Error responses use the envelope and codes of §2.2 and §5.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/ag-drone/subscription-plans` | Create a subscription plan | OpsAdmin |
| GET | `/ag-drone/subscription-plans/{id}` | Get a subscription plan | OpsAdmin, FlightCoordinator, Grower |
| GET | `/ag-drone/subscription-plans` | List subscription plans | OpsAdmin, FlightCoordinator, Grower |
| POST | `/ag-drone/growers` | Register a grower | OpsAdmin |
| GET | `/ag-drone/growers/{id}` | Get a grower | OpsAdmin, FlightCoordinator, Grower, ClaimsAdjuster |
| GET | `/ag-drone/growers` | List growers | OpsAdmin, FlightCoordinator |
| PATCH | `/ag-drone/growers/{id}` | Update grower subscription plan or liability coverage (OCC) | OpsAdmin |
| POST | `/ag-drone/growers/{id}/suspend` | Suspend a grower; cancels non-terminal missions | OpsAdmin |
| POST | `/ag-drone/growers/{id}/reinstate` | Reinstate a suspended grower | OpsAdmin |
| POST | `/ag-drone/growers/{id}/terminate` | Terminate a suspended grower | OpsAdmin |
| POST | `/ag-drone/growers/{id}/invoice` | Run monthly invoice; settles FINAL billing and debits credit balance | OpsAdmin |
| POST | `/ag-drone/growers/{id}/fields` | Create a field under a grower | OpsAdmin, Grower |
| GET | `/ag-drone/fields/{id}` | Get a field | OpsAdmin, FlightCoordinator, Grower, Agronomist, RemotePilot |
| GET | `/ag-drone/growers/{id}/fields` | List fields for a grower | OpsAdmin, FlightCoordinator, Grower |
| POST | `/ag-drone/pilots` | Register a pilot profile | OpsAdmin |
| GET | `/ag-drone/pilots/{id}` | Get a pilot | OpsAdmin, FlightCoordinator, RemotePilot, Agronomist |
| GET | `/ag-drone/pilots` | List pilots | OpsAdmin, FlightCoordinator |
| POST | `/ag-drone/airspace-authorizations` | Register a LAANC authorization for a field | OpsAdmin, FlightCoordinator |
| GET | `/ag-drone/airspace-authorizations/{id}` | Get an authorization | OpsAdmin, FlightCoordinator, RemotePilot |
| GET | `/ag-drone/airspace-authorizations` | List authorizations | OpsAdmin, FlightCoordinator, RemotePilot |
| POST | `/ag-drone/airspace-authorizations/{id}/revoke` | Revoke an ACTIVE authorization | OpsAdmin |
| POST | `/ag-drone/fields/{id}/missions` | Plan a new mission on a field | FlightCoordinator |
| GET | `/ag-drone/missions/{id}` | Get a mission | OpsAdmin, FlightCoordinator, Grower, RemotePilot, Agronomist, ClaimsAdjuster |
| GET | `/ag-drone/fields/{id}/missions` | List missions on a field | OpsAdmin, FlightCoordinator, Grower, RemotePilot |
| GET | `/ag-drone/missions` | List missions across fields | OpsAdmin, FlightCoordinator |
| POST | `/ag-drone/missions/{id}/authorize` | Authorize a PLANNED mission | FlightCoordinator |
| POST | `/ag-drone/missions/{id}/launch` | Launch an AUTHORIZED mission; must be the assigned pilot | RemotePilot |
| POST | `/ag-drone/missions/{id}/capture` | Record capture results and move to CAPTURED | RemotePilot |
| POST | `/ag-drone/missions/{id}/abort-weather` | Abort an IN_FLIGHT mission for weather | RemotePilot |
| POST | `/ag-drone/missions/{id}/complete` | Complete a CAPTURED mission; billing, deliverables, spray record | FlightCoordinator |
| POST | `/ag-drone/missions/{id}/cancel` | Cancel a PLANNED or AUTHORIZED mission | FlightCoordinator |
| POST | `/ag-drone/missions/{id}/replan` | Replan a disrupted mission into a fresh PLANNED revision (OCC) | FlightCoordinator |
| GET | `/ag-drone/deliverables/{id}` | Get a deliverable (grower access gated by accessible_until) | OpsAdmin, FlightCoordinator, Grower, Agronomist, ProcessingEngine |
| GET | `/ag-drone/missions/{id}/deliverables` | List deliverables for a mission | OpsAdmin, FlightCoordinator, Grower, Agronomist, ProcessingEngine |
| POST | `/ag-drone/deliverables/{id}/process` | Submit processing outputs; moves to READY; may raise a scouting alert | ProcessingEngine |
| POST | `/ag-drone/deliverables/{id}/deliver` | Mark a READY deliverable as delivered to the grower | FlightCoordinator |
| GET | `/ag-drone/alerts/{id}` | Get an alert | OpsAdmin, FlightCoordinator, Grower, Agronomist |
| GET | `/ag-drone/fields/{id}/alerts` | List alerts on a field | OpsAdmin, FlightCoordinator, Grower, Agronomist |
| GET | `/ag-drone/alerts` | List alerts across fields | OpsAdmin, FlightCoordinator, Agronomist |
| POST | `/ag-drone/alerts/{id}/claim` | Agronomist claims an OPEN alert | Agronomist |
| POST | `/ag-drone/alerts/{id}/review` | Claiming agronomist submits review outcome | Agronomist |
| POST | `/ag-drone/alerts/{id}/release` | Claiming agronomist releases the alert back to OPEN | Agronomist |
| GET | `/ag-drone/missions/{id}/spray-record` | Get the immutable spray record for a SPRAY mission (array of 0 or 1) | OpsAdmin, FlightCoordinator, Grower, ClaimsAdjuster |
| POST | `/ag-drone/growers/{id}/claims` | Submit an insurance claim against a mission | Grower |
| GET | `/ag-drone/claims/{id}` | Get a claim | OpsAdmin, Grower, ClaimsAdjuster |
| GET | `/ag-drone/claims` | List claims across growers | OpsAdmin, ClaimsAdjuster |
| GET | `/ag-drone/growers/{id}/claims` | List claims for a grower | OpsAdmin, Grower, ClaimsAdjuster |
| POST | `/ag-drone/claims/{id}/open-review` | Adjuster opens review | ClaimsAdjuster |
| POST | `/ag-drone/claims/{id}/approve` | Adjuster approves claim with amount | ClaimsAdjuster |
| POST | `/ag-drone/claims/{id}/deny` | Adjuster denies claim | ClaimsAdjuster |
| POST | `/ag-drone/claims/{id}/pay` | Pay an APPROVED claim; credits the grower credit balance | ClaimsAdjuster |
| POST | `/ag-drone/_clock/set_current_utc` | Set the server's logical clock | OpsAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_CONTEXT` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_GROWER_NOT_ACTIVE` | 409 Conflict |
| `ERR_GROWER_NOT_SUSPENDED` | 409 Conflict |
| `ERR_MISSION_IN_FLIGHT` | 409 Conflict |
| `ERR_MISSION_NOT_PLANNED` | 409 Conflict |
| `ERR_MISSION_NOT_AUTHORIZED` | 409 Conflict |
| `ERR_MISSION_NOT_IN_FLIGHT` | 409 Conflict |
| `ERR_MISSION_NOT_CAPTURED` | 409 Conflict |
| `ERR_MISSION_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_DELIV_NOT_PROCESSING` | 409 Conflict |
| `ERR_DELIV_NOT_READY` | 409 Conflict |
| `ERR_ALERT_NOT_OPEN` | 409 Conflict |
| `ERR_ALERT_NOT_UNDER_REVIEW` | 409 Conflict |
| `ERR_CLAIM_NOT_SUBMITTED` | 409 Conflict |
| `ERR_CLAIM_NOT_UNDER_REVIEW` | 409 Conflict |
| `ERR_CLAIM_NOT_APPROVED` | 409 Conflict |
| `ERR_AUTH_NOT_ACTIVE` | 409 Conflict |
| `ERR_PILOT_CERT_EXPIRED` | 422 Unprocessable Entity |
| `ERR_SPRAY_PLAN_FORBIDDEN` | 422 Unprocessable Entity |
| `ERR_AUTH_WINDOW_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_AUTH_NOT_PERMITTED` | 422 Unprocessable Entity |
| `ERR_WEATHER_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_WEATHER_LIMIT_NOT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_ACRES_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_MISSION_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_OUTSIDE_WINDOW` | 422 Unprocessable Entity |
| `ERR_DELIV_EXPIRED` | 410 Gone |
| `ERR_DELIV_INPUT_INVALID` | 422 Unprocessable Entity |
| `ERR_SELF_REVIEW_FORBIDDEN` | 422 Unprocessable Entity |
| `ERR_NOT_CLAIMING_AGRONOMIST` | 403 Forbidden |
| `ERR_NOT_ASSIGNED_PILOT` | 403 Forbidden |
| `ERR_REVIEW_OUTCOME_INVALID` | 422 Unprocessable Entity |
| `ERR_CLAIM_EXCEEDS_COVERAGE` | 422 Unprocessable Entity |
| `ERR_CLAIM_MISSION_NOT_FINAL` | 409 Conflict |
| `ERR_STALE_MISSION_VERSION` | 412 Precondition Failed |
| `ERR_STALE_GROWER_VERSION` | 412 Precondition Failed |

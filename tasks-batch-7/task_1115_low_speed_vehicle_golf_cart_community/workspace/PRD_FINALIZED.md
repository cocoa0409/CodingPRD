# Low-Speed Vehicle & Golf Cart Community Program API — Product Requirements Document

## 1. Introduction

Residential communities are increasingly adopting local ordinances that welcome low-speed vehicles and golf carts onto designated streets and paths, and every such ordinance creates an administrative burden: someone must decide which residents may drive, which vehicles are safe, which streets and paths are open, and what happens when the rules are broken. This document specifies the API for a Low-Speed Vehicle & Golf Cart Community Program — the administrative backbone a community uses to run that ordinance end to end. The system governs community eligibility rules and street designation, annual vehicle registration with safety-equipment requirements, driver age and license verification, inspection scheduling and scoring, insurance documentation, route and path access passes, charging infrastructure, an optional shared fleet, violation enforcement with points-based standing, and the annual renewal cycle.

Two design tensions shape every workflow that follows. First, the program is fundamentally an audit system: holder standing, registration status, and fee amounts are all derived from verifiable records (inspections, violations, insurance policies, fleet usage history), and enforcement actions cascade outward — a single upheld citation can suspend registrations and revoke route passes several hops away. Second, the program is saturated with time windows whose boundary semantics differ deliberately: route passes are half-open so that back-to-back bookings are possible, charging reservations are closed intervals padded with a turnaround buffer, fleet shifts are closed intervals where adjacency itself counts as a conflict, and renewals distinguish an in-window renewal from a late-grace renewal with different fee consequences. All temporal behavior is evaluated against a controllable logical clock rather than the wall clock, so that expiry, completion, and overdue transitions are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to declare their operational capacity. The system recognizes six roles, spelled exactly as follows: `Anonymous`, `PlatformAdmin`, `CommunityAdmin`, `Inspector`, `EnforcementOfficer`, and `PermitHolder`. A request whose headers are missing, or whose `X-User-Role` is not one of these declared values, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401); the sole exception is permit-holder self-registration, which an `Anonymous` caller may perform without headers. A request whose role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `PermitHolder`, `X-User-ID` is the `id` of the acting PermitHolder; ownership checks on any resource that references a PermitHolder compare the resource's holder foreign-key field to `X-User-ID`, and a PermitHolder-role call acting on a resource owned by another holder is rejected with `ERR_FORBIDDEN`. When `X-User-Role` is `Anonymous`, `PlatformAdmin`, `CommunityAdmin`, `Inspector`, or `EnforcementOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit purposes but never compares it to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

Many list endpoints additionally accept an optional foreign-key filter restricting the listing to children of a given parent — for example `community_id` on the permit-holder, route, charging-station, and fleet-vehicle listings, `holder_id` on the vehicle, registration, insurance-policy, route-pass, charging-reservation, fleet-dispatch, and violation listings, `vehicle_id` on the registration, insurance-policy, and fleet-dispatch listings, `registration_id` on the inspection, route-pass, and violation listings, `route_id` on the route-pass listing, and `station_id` on the charging-reservation and fleet-vehicle listings.

### 2.4. The Logical Clock and Time-Driven Transitions

Every rule in this document that speaks of "now", "today", an age, a trailing window, or an overdue duration refers to a server-side **logical clock**, never the host wall clock. At server startup the logical clock reads exactly 2026-05-01T00:00:00Z. A `PlatformAdmin`-only test-driving capability, mounted outside the `/api` prefix, advances the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`; each such advance evaluates every time-driven transition in the system before the response is returned.

The time-driven transitions are: a registration in `ACTIVE` flips to `EXPIRED` once the clock moves past its `expiry_date`; a registration in `RENEWAL_PENDING` flips to `EXPIRED` once the clock moves past the end of its late-grace period (its `expiry_date` plus the community's `late_grace_days`); a route pass in `ACTIVE` flips to `COMPLETED` when the clock reaches its `end_at`; a charging reservation in `BOOKED` flips to `COMPLETED` once the clock moves strictly past its `end_at`; a fleet dispatch in `CHECKED_OUT` flips to `OVERDUE` once the clock moves past its `shift_end`; and an insurance policy in `ACTIVE` flips to `EXPIRED` once the current date is later than its `expiry_date` (the expiry date itself is the last covered day).

### 2.5. Common Resource Properties and Mutation Semantics

Every resource in the system carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is first created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed upon any change to the resource's properties.
- `version` (integer): a system-managed integer that starts at 1 on creation and increments by 1 with every mutation of the resource.

All datetime-valued fields the server serializes — `created_at`, `updated_at`, a registration's `valid_from` and `expiry_date`, an inspection's `scheduled_at`, a route pass's or charging reservation's `start_at` and `end_at`, a fleet dispatch's `shift_start`, `shift_end`, and `returned_at`, a violation's `occurred_at`, and the clock endpoint's `current_utc` — use one format: ISO 8601 UTC with exactly three fractional digits and a trailing `Z` (for example `2026-05-01T00:00:00.000Z`). Date-valued fields such as `birth_date` and an insurance policy's `effective_date` and `expiry_date` are ISO 8601 dates, not datetimes, and are not subject to this format.

Lifecycle-bearing resources additionally expose a `status` field (named `designation_status` on routes and `vehicle_status` on vehicles) whose value is always one of the exact UPPERCASE enumeration strings used throughout §3.

A mutation is any change to a resource's stored fields, including changes driven by cascades: when one operation flips several resources (for example, revoking a holder's registrations and their route passes), each affected resource independently refreshes its `updated_at` and increments its `version`. Every mutation — including all of its cascades — is applied atomically within the request and is fully visible in the response.

### 2.6. Request Validation Pipeline and Error Precedence

Every request is evaluated against an ordered pipeline of ten validation stages. The pipeline short-circuits at the first stage that fails: the error raised by that stage is the one returned, and later stages are never consulted. The stages, in evaluation order, are:

1. **Request-body schema** — all required fields are present, enum values are in range, integers fall within their declared ranges, and on every windowed payload the window end is strictly after its start. Failure: `ERR_VALIDATION` (HTTP 400).
2. **Authentication** — `X-User-Role` and `X-User-ID` are present and the role is a declared role. Failure: `ERR_UNAUTHENTICATED` (HTTP 401). Permit-holder self-registration is exempt; `Anonymous` is allowed there.
3. **Authorization** — the role is permitted for the endpoint, and for `PermitHolder`-role calls `X-User-ID` equals the owning holder of the target or payload resource. Failure: `ERR_FORBIDDEN` (HTTP 403).
4. **Existence** — every identifier referenced in the path and body exists. Identifiers are validated left to right: path parameters first, then body foreign keys in their declared field order. Failure: `ERR_NOT_FOUND` (HTTP 404).
5. **State and concurrency** — the target resource's own state machine permits the requested transition from its current state, and any OCC version field matches the stored version. A state-machine failure is rejected with `ERR_INVALID_STATE` (HTTP 409); an OCC version mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412) instead.
6. **Safety gates** — driver age and license class at eligibility verification (`ERR_UNDERAGE_DRIVER`, `ERR_LICENSE_CLASS_INSUFFICIENT`), vehicle equipment minimums at registration creation (`ERR_EQUIPMENT_MINIMUM`), and vehicle-class admissibility on the route at pass booking (`ERR_ROUTE_VEHICLE_CLASS`), all HTTP 422.
7. **Temporal windows and overlaps** — renewal attempted outside its window or grace period (`ERR_RENEWAL_WINDOW_CLOSED`, HTTP 422), route-pass window collision (`ERR_ROUTE_PASS_OVERLAP`, HTTP 409), charging-slot collision (`ERR_CHARGING_OVERLAP`, HTTP 409), and dispatch-window collision (`ERR_DISPATCH_WINDOW_OVERLAP`, HTTP 409).
8. **Cross-entity state gates** — holder not `ELIGIBLE` where required (`ERR_HOLDER_NOT_ELIGIBLE`), holder `BARRED` where that blocks the action (`ERR_HOLDER_BARRED`), registration not `ACTIVE` at pass booking (`ERR_REGISTRATION_NOT_ACTIVE`), no passing inspection at activation or reinstatement (`ERR_INSPECTION_NOT_PASSED`), required insurance absent (`ERR_INSURANCE_MISSING`), route not `DESIGNATED` (`ERR_ROUTE_NOT_DESIGNATED`), station not `ONLINE` (`ERR_STATION_OFFLINE`), fleet vehicle not `AVAILABLE` at checkout (`ERR_FLEET_UNAVAILABLE`). All are HTTP 422 except `ERR_STATION_OFFLINE` and `ERR_FLEET_UNAVAILABLE`, which are HTTP 409.
9. **Uniqueness and domain constraints** — a duplicate annual registration for the same vehicle and year (`ERR_DUPLICATE_REGISTRATION`, HTTP 409), and an insurance policy whose documented coverage is below the community minimum (`ERR_INSURANCE_COVERAGE_LOW`, HTTP 422).
10. **Wallet sufficiency** — the holder's `wallet_balance_cents` covers the amount about to be debited. Failure: `ERR_INSUFFICIENT_FUNDS` (HTTP 402).

### 2.7. Optimistic Concurrency Control

Exactly two write operations carry an optimistic-concurrency guard, each keyed to the current `version` of a parent entity.

Updating a community's configuration requires the request body to carry `expected_community_version`, set to the community `version` the client last observed. If a prior accepted update has since advanced the community's `version` — so the fee-relevant thresholds and renewal windows the client read are stale — the update is rejected with `ERR_STALE_VERSION` (HTTP 412) and must be re-based on a fresh read.

Depositing into a holder's wallet requires the request body to carry `expected_permit_holder_version`, set to the PermitHolder `version` the client last observed. Deposits are always semantically valid, so this stale-version check is the only guard against a lost update when another mutation — a fee debit, a cascade refund, a prior deposit — has advanced the holder's `version` since the client's last read. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts a version field.

### 2.8. Money, Scores, and Rounding Discipline

All monetary values are integers denominated in cents. Wherever fee arithmetic multiplies two numbers, each multiplication is rounded half-up to whole cents before the next step of the calculation proceeds, and fee floors and caps are applied after that rounding. Day counts used in late-fee and overdue-fine computations are whole days: partial days are discarded by flooring when measuring days overdue, and rounded up when billing fractional days late on a fleet return. Charging durations are measured in minutes with any fractional minute rounded up before the per-minute rate is applied.

Scores carry their own precision rules. An inspection's component contributions are each rounded half-up to two decimal places before being summed, and the inspection `total_score` is the exact sum of those rounded contributions. The renewal compliance score is rounded half-up to two decimal places on the final value only, and is never allowed to fall below zero.

### 2.9. The Holder Wallet as a Prepaid Ledger

Each permit holder carries a prepaid `wallet_balance_cents` that starts at zero and can never go negative. The wallet is credited by holder deposits and by refunds — a cancelled charging reservation returns its fee in full, as does each reservation cancelled by a station outage cascade. The wallet is debited by the registration activation charge, the renewal finalization charge, the charging fee at booking time, and the fleet late fine at return time. Any debit is permitted when the balance equals the amount due — equality is sufficient — and is rejected with `ERR_INSUFFICIENT_FUNDS` (HTTP 402) when the balance falls short. Citation fines recorded on violations are an informational ledger only and are never auto-debited from the wallet.

### 2.10. Interval and Overlap Semantics for Time-Windowed Resources

Three resource families reserve time, and each uses deliberately different interval semantics.

**Route passes** occupy a half-open window: the pass holds from its `start_at` inclusive up to but not including its `end_at`. Two passes on the same registration may therefore touch — one beginning at the exact instant the other ends — but any true overlap between the new window and another `ACTIVE` pass on the same registration is rejected with `ERR_ROUTE_PASS_OVERLAP` (HTTP 409).

**Charging reservations** occupy a closed interval — both `start_at` and `end_at` inclusive — padded with a 15-minute turnaround buffer on both sides. A new reservation on a given station and bay collides with any other `BOOKED` reservation on the same station and `slot_index` whose buffered interval touches it; such a collision is rejected with `ERR_CHARGING_OVERLAP` (HTTP 409).

**Fleet dispatch shifts** occupy a closed interval from `shift_start` through `shift_end` with no buffer, and per vehicle adjacency itself counts as a conflict: a new dispatch whose closed window so much as touches another non-terminal dispatch on the same vehicle is rejected with `ERR_DISPATCH_WINDOW_OVERLAP` (HTTP 409).

On every windowed payload, the window end must be strictly after the window start, or the request fails schema validation with `ERR_VALIDATION`.

### 2.11. Cascading Consistency Across the Program

Status changes propagate outward so that no dependent resource outlives the authority that justified it. Suspending or revoking a registration revokes every `ACTIVE` route pass issued against it. Revoking a holder's eligibility revokes each of the holder's registrations in `ACTIVE`, `RENEWAL_PENDING`, or `SUSPENDED` status, and each of those revocations in turn revokes its `ACTIVE` route passes. A holder whose standing flips into `BARRED` has every `ACTIVE` registration suspended, with the same route-pass revocations following each suspension. Decommissioning a route revokes every `ACTIVE` pass booked on it. Taking a charging station offline cancels every future `BOOKED` reservation on it and refunds each fee. Moving a fleet vehicle to maintenance cancels every future `BOOKED` dispatch naming it.

Cascades are strictly one-directional and never resurrect. Reinstating a suspended registration leaves its previously revoked route passes `REVOKED`; a holder who drops out of `BARRED` through a dismissal keeps their suspended registrations suspended until an administrator reinstates them one by one.

## 3. Business Logic & Workflows

### 3.1. Community Setup and Program Parameters

A `PlatformAdmin` opens a new community program by supplying its display `name`. Six optional parameters tune the ordinance and each carries a default applied when omitted: `min_driver_age` is the minimum driver age in whole years (an integer from 12 to 25, default 16); `insurance_required` decides whether an `ACTIVE` insurance policy is required to activate or reinstate a registration (default true); `fleet_program_enabled` decides whether the shared fleet option is offered, and also gates the fleet-discount assumption inside provisional fee quotes (default false); `min_liability_coverage_cents` is the minimum liability coverage an insurance policy must document (default 10000000 cents); `renewal_window_days` sets how many days before expiry a renewal opens, with the opening boundary inclusive (default 60); and `late_grace_days` sets how many days after expiry a late renewal remains possible, again with an inclusive boundary (default 90). A freshly created community also carries a computed `checked_out_count` starting at zero, tracking how many of its fleet vehicles are currently checked out.

A `PlatformAdmin` may later update any of these configuration fields. Because fee thresholds and renewal windows feed live calculations, the update is guarded by optimistic concurrency as specified in §2.7 and increments the community's `version` by 1 on success.

### 3.2. Permit Holder Onboarding and the Two Standing Dimensions

A resident joins the program through self-registration — open to `Anonymous` callers, and also available to a `CommunityAdmin` registering on someone's behalf — by supplying the `community_id` of their community, their legal `full_name`, their `birth_date` as an ISO 8601 date, and their `driver_license_class`, one of `NONE`, `STANDARD`, or `MOTORCYCLE`. The new holder starts with `eligibility_status` `PENDING_VERIFICATION`, `compliance_status` `GOOD_STANDING`, a `points_balance` of zero, and an empty `wallet_balance_cents`.

Every PermitHolder row carries two independent state dimensions. The first, `eligibility_status`, moves through `PENDING_VERIFICATION`, `ELIGIBLE`, `SUSPENDED`, and the terminal `REVOKED` under administrator control. The second, `compliance_status`, moves through `GOOD_STANDING`, `PROBATION`, and `BARRED`; it is never written directly and is instead recomputed from the holder's `points_balance` whenever violation adjudication changes that balance. An action gated on one dimension says nothing about the other: suspending a holder's eligibility leaves their compliance standing untouched.

Eligibility verification is performed by a `CommunityAdmin`. The holder's age is the floor of the whole years between `birth_date` and today on the logical clock, and must be at least the community's `min_driver_age` — a resident verifying on their exact minimum-age birthday passes. An underage holder is rejected with `ERR_UNDERAGE_DRIVER` (HTTP 422). Independently, a holder whose `driver_license_class` is `NONE` cannot be verified and is rejected with `ERR_LICENSE_CLASS_INSUFFICIENT` (HTTP 422). A successful verification moves the holder `PENDING_VERIFICATION` → `ELIGIBLE` and increments the holder's `version`.

Thereafter a `CommunityAdmin` may suspend an `ELIGIBLE` holder (`ELIGIBLE` → `SUSPENDED`), reinstate a `SUSPENDED` holder (`SUSPENDED` → `ELIGIBLE`), or revoke a holder in either `ELIGIBLE` or `SUSPENDED` status (`ELIGIBLE` → `REVOKED` or `SUSPENDED` → `REVOKED`). Revocation is terminal and triggers the registration and route-pass cascade described in §2.11. Each of these eligibility mutations increments the holder's `version`.

Holders fund their own wallets. A deposit names an `amount_cents` and must carry the OCC field described in §2.7; a successful deposit adds the amount to `wallet_balance_cents` and increments the holder's `version`.

### 3.3. Vehicles, Equipment Declarations, and Registration Drafting

A holder registers a vehicle by declaring its `holder_id`, its `vehicle_type` — `GOLF_CART` or `LSV` — its `seat_count` (from 1 to 8), seven boolean equipment flags (`has_headlights`, `has_brake_lights`, `has_turn_signals`, `has_horn`, `has_windshield`, `has_seatbelts`, `has_reflectors`), and a `mirror_count` from 0 to 4, where zero means the vehicle has no mirrors at all. From this declaration the system computes `equipment_count`: the number of the seven boolean flags that are true, plus one more when at least one mirror is installed, yielding a value from 0 to 8. A vehicle's `vehicle_status` begins `ACTIVE`. A holder may retire an `ACTIVE` vehicle — `ACTIVE` → `RETIRED`, terminal — only when the vehicle has no registration in `DRAFT`, `ACTIVE`, `RENEWAL_PENDING`, or `SUSPENDED` status; `EXPIRED` and `REVOKED` registrations do not block retirement.

With a vehicle on file, the holder drafts an annual registration by supplying `vehicle_id`, `holder_id`, and a `registration_year` between 2020 and 2100. The `holder_id` on the request must equal the holder who owns the referenced vehicle. At creation the system enforces class-specific equipment minimums: a `GOLF_CART` must declare headlights and brake lights; an `LSV` must declare headlights, brake lights, seatbelts, and at least one mirror. A vehicle falling short of its class minimum is rejected with `ERR_EQUIPMENT_MINIMUM` (HTTP 422). Creation also enforces annual uniqueness: no second registration may exist for the same vehicle and `registration_year` while any earlier registration for that pair is not yet `REVOKED` — including one that is merely `EXPIRED`. A violating create is rejected with `ERR_DUPLICATE_REGISTRATION` (HTTP 409).

A new registration starts in `DRAFT`. Creation computes the provisional annual fee from the declared equipment (the PROVISIONAL variant of §3.5) and stores it in `provisional_fee_cents`. The remaining fiscal fields settle into their initial state: `finalized_fee_cents` is null until an inspection passes (or a late renewal recomputes it), `late_fee_cents` is zero, `total_due_cents` starts at zero and is populated once the finalized fee first exists, `paid_cents` is zero, both `renewal_score_provisional` and `renewal_score_audited` are null, and `valid_from` and `expiry_date` are null until first activation.

### 3.4. Safety Inspections and Scored Outcomes

An `Inspector` schedules an inspection for a registration by naming its `registration_id` and a `scheduled_at` instant; the inspection starts `SCHEDULED`. Finalization, also by an `Inspector`, records eight component scores — `headlights_score`, `brake_lights_score`, `turn_signals_score`, `horn_score`, `mirrors_score`, `windshield_score`, `seatbelts_score`, and `reflectors_score` — each an integer from 0 to 100. Finalization is only permitted while the referenced registration is in `DRAFT`, `ACTIVE`, `RENEWAL_PENDING`, or `SUSPENDED` status; attempts against `EXPIRED` or `REVOKED` registrations are rejected with `ERR_INVALID_STATE`.

The inspection's `total_score` is a weighted blend with per-component rounding. Each component carries a fixed weight: headlights 16.67 percent, brake lights 16.67 percent, turn signals 13.33 percent, horn 6.67 percent, mirrors 10.00 percent, windshield 10.00 percent, seatbelts 16.66 percent, and reflectors 10.00 percent. For each component, the component's score is multiplied by its weight percent and divided by 100, and that contribution is rounded half-up to two decimal places before any summation. The `total_score` is the exact sum of the eight rounded contributions. The `passed` flag is true when `total_score` is at least 70.00 — a score of exactly 70.00 passes. Until finalization, both `total_score` and `passed` are null.

The outcome drives the registration. A finalized inspection whose total meets the threshold becomes `PASSED` — terminal — and triggers a recomputation of the registration's `finalized_fee_cents` using the FINALIZED variant of §3.5, with `total_due_cents` reset to the smaller of the finalized fee plus the late fee and twice the finalized fee. A finalized inspection below the threshold becomes `FAILED` — also terminal — and if the referenced registration is currently `ACTIVE`, the failure cascades: the registration flips to `SUSPENDED` and every `ACTIVE` route pass issued against it flips to `REVOKED`.

### 3.5. Insurance Documentation and Registration Activation

A holder documents an insurance policy by supplying `holder_id`, `vehicle_id`, the `provider_name`, the `policy_number`, the `liability_coverage_cents` documented, an `effective_date`, and an `expiry_date` on which coverage ends inclusively. The documented coverage must be at least the community's `min_liability_coverage_cents`, or creation is rejected with `ERR_INSURANCE_COVERAGE_LOW` (HTTP 422). A policy starts `ACTIVE`; the holder may cancel an `ACTIVE` policy (`ACTIVE` → `CANCELLED`), and the logical clock flips an `ACTIVE` policy to `EXPIRED` per §2.4. Both `CANCELLED` and `EXPIRED` are terminal.

The annual registration fee has two variants built from one formula. The base is 7500 cents for a `GOLF_CART` and 15000 cents for an `LSV`. An equipment multiplier starts at 1 and grows by a per-item rate for each counted equipment item in the vehicle's `equipment_count`, capped so the multiplier never exceeds 1.20; the per-item rate is 0.02 for the PROVISIONAL variant and 0.025 for the FINALIZED variant. A seat surcharge adds 500 cents for every seat beyond the first four — the first four seats are free. The subtotal is the base multiplied by the capped multiplier, rounded half-up to whole cents, plus the seat surcharge. When the fleet discount applies, the subtotal is then multiplied by 0.90 — a ten percent discount — and rounded half-up to whole cents again. The fee is the larger of that subtotal and the base: the fee never falls below the base amount.

The variants differ only in how the fleet discount is decided. The PROVISIONAL variant — used at registration creation and at a renewal opened while the registration is still `ACTIVE` — assumes the discount whenever the community's `fleet_program_enabled` is true, with no usage-history check. The FINALIZED variant — used when an inspection passes, when a late renewal is opened from `EXPIRED`, and at renewal finalization — grants the discount only when the holder has at least one fleet dispatch in `RETURNED` status whose `returned_at` falls within the trailing 365 days of the calculation instant.

Activation moves a registration `DRAFT` → `ACTIVE` and is performed by the holder. It is gated on the full compliance picture: the most recently finalized inspection for the registration must be `PASSED` (otherwise `ERR_INSPECTION_NOT_PASSED`, HTTP 422); when the community's `insurance_required` is true, an `ACTIVE` policy must cover the registration's vehicle (otherwise `ERR_INSURANCE_MISSING`, HTTP 422); the holder must be `ELIGIBLE` (otherwise `ERR_HOLDER_NOT_ELIGIBLE`, HTTP 422) and must not be `BARRED` (otherwise `ERR_HOLDER_BARRED`, HTTP 422); and the wallet must hold at least `total_due_cents` — for a fresh draft this equals the finalized fee, and a balance exactly equal to the amount due is sufficient (otherwise `ERR_INSUFFICIENT_FUNDS`, HTTP 402). On success the wallet is debited by `total_due_cents`, the registration's `paid_cents` accumulates that same amount, `valid_from` is set to the activation instant, `expiry_date` is set 365 days after `valid_from`, and both the registration's and the holder's `version` increment by 1.

### 3.6. The Renewal Cycle: Windows, Late Grace, and the Compliance Audit

When the logical clock moves past a registration's `expiry_date`, an `ACTIVE` registration flips to `EXPIRED`. Renewal can be opened from either side of that boundary, with different economics.

A renewal opened while the registration is `ACTIVE` requires the current instant to fall within the renewal window: from `renewal_window_days` days before `expiry_date` through `expiry_date` itself, both bounds inclusive. The holder must not be `BARRED`. Opening this renewal moves the registration `ACTIVE` → `RENEWAL_PENDING`, recomputes `provisional_fee_cents` via the PROVISIONAL variant, records a `renewal_score_provisional` evaluated as of the renew instant, sets `late_fee_cents` to zero, and leaves `total_due_cents` unchanged until finalization.

A late renewal opened while the registration is `EXPIRED` requires the current instant to be after `expiry_date` and no later than `late_grace_days` days past it — the lower bound exclusive, the upper bound inclusive. The holder must not be `BARRED`. Opening a late renewal moves the registration `EXPIRED` → `RENEWAL_PENDING`, recomputes `finalized_fee_cents` via the FINALIZED variant against the vehicle's current data, computes a late fee, and sets `total_due_cents` to the smaller of the finalized fee plus the late fee and twice the finalized fee. A renewal attempted outside both the window and the grace period is rejected with `ERR_RENEWAL_WINDOW_CLOSED` (HTTP 422).

The late fee follows a pinned evaluation order, so the circular-looking dependency between fee, tier, late amount, cap, and total is well-defined. First, the finalized fee is taken as the base. Second, the base selects a tier: tier A when the base is below 10000 cents, tier B otherwise. Third, the days overdue are the whole days between `expiry_date` and now, partial days discarded. Fourth, the days overdue select a band: 30 days or fewer lands in the first band (day 30 exactly is band one), 31 through 60 days lands in the second, and 61 days through `late_grace_days` lands in the third. The raw late fee for tier A is 1500, 3000, or 6000 cents by band; for tier B it is 2500, 5000, or 10000 cents. Fifth, the total due is the smaller of the base plus the raw late fee and twice the base — the combined charge never exceeds double the finalized fee.

The renewal compliance score is computed in two variants from the holder's violation history, both evaluated as 100 minus a weighted penalty sum, floored at zero, with the final score rounded half-up to two decimal places. Each included violation contributes its `points_assessed` multiplied by a recency weight multiplied by a status weight. The recency weight is full (1.0) when the violation's `occurred_at` lies within the trailing 180 days of the as-of instant, half (0.5) when it lies within the trailing 365 days, and violations older than 365 days are excluded entirely. The PROVISIONAL variant, computed at the renew instant, includes only violations in `UPHELD` status at a status weight of 1.0; `FILED` violations are excluded entirely. The AUDITED variant, computed at the finalization instant, includes `UPHELD` violations at weight 1.0 and additionally includes `FILED` violations whose `occurred_at` is more than 30 days before the as-of instant, at a status weight of 0.5. A renewal passes when its score is at least 70 — exactly 70 passes.

Renewal finalization is the audit step, performed by a `CommunityAdmin` against a registration in `RENEWAL_PENDING`. The audited score is computed within the request, the finalized fee and total due are recomputed at the same instant, and `renewal_score_audited` is recorded. When the audited score is at least 70, the registration moves `RENEWAL_PENDING` → `ACTIVE`: the wallet is debited the recomputed total due (a shortfall is rejected with `ERR_INSUFFICIENT_FUNDS`), `paid_cents` accumulates the debit, `expiry_date` extends by 365 days from the previous expiry, and both the registration's and the holder's `version` increment. When the audited score falls below 70, the registration instead moves `RENEWAL_PENDING` → `SUSPENDED`: the audited score is still recorded, but no wallet debit occurs and `expiry_date` is left unchanged.

Outside the renewal flow, a `CommunityAdmin` may suspend an `ACTIVE` registration (`ACTIVE` → `SUSPENDED`), which revokes its `ACTIVE` route passes per §2.11. Reinstatement (`SUSPENDED` → `ACTIVE`) requires the holder not to be `BARRED`, the most recently finalized inspection to be `PASSED`, and — when the community requires insurance — an `ACTIVE` policy covering the vehicle; passes revoked earlier stay `REVOKED`. An `EnforcementOfficer` may revoke a registration in `ACTIVE`, `RENEWAL_PENDING`, `SUSPENDED`, or `EXPIRED` status; `REVOKED` is terminal, and revocation from any of the first three states revokes the registration's `ACTIVE` route passes.

### 3.7. Street Designation and Route Passes

A `CommunityAdmin` designates streets and paths by creating routes with a `community_id`, a `name`, a `route_type` of `STREET` or `PATH`, and an `allowed_vehicle_class` of `GOLF_CART_ONLY` — carts only — or `LSV_ALLOWED`, which admits both carts and low-speed vehicles. A route's `designation_status` starts `DESIGNATED`. Decommissioning flips it to `DECOMMISSIONED` (terminal) and revokes every `ACTIVE` pass booked on it.

A holder books a route pass by supplying `route_id`, `registration_id`, `holder_id`, `start_at`, and `end_at`. Booking requires the route to be `DESIGNATED` (otherwise `ERR_ROUTE_NOT_DESIGNATED`, HTTP 422), the registration to be `ACTIVE` (otherwise `ERR_REGISTRATION_NOT_ACTIVE`, HTTP 422), and the holder to be `ELIGIBLE` (otherwise `ERR_HOLDER_NOT_ELIGIBLE`). The `holder_id` on the request must equal the holder recorded on the referenced registration. A registration for an `LSV` may not book a `GOLF_CART_ONLY` route; the attempt is rejected with `ERR_ROUTE_VEHICLE_CLASS` (HTTP 422). The requested window must also respect the half-open overlap rule of §2.10 against the registration's other `ACTIVE` passes.

A pass starts `ACTIVE`. The holder may cancel it — `ACTIVE` → `CANCELLED` — only before its window begins; once the clock has reached `start_at`, cancellation is rejected with `ERR_INVALID_STATE`. A pass whose window runs its course completes when the clock reaches its `end_at` (`ACTIVE` → `COMPLETED`), and a pass caught by any cascade of §2.11 flips to `REVOKED`. All three of `CANCELLED`, `REVOKED`, and `COMPLETED` are terminal.

### 3.8. Charging Infrastructure and the Shared Fleet

A `CommunityAdmin` builds out charging infrastructure by creating stations with a `community_id`, a display `name`, a `slot_count` from 1 to 20 bays, and a `rate_cents_per_min` of at least 1 cent per minute. A station starts `ONLINE`. Taking a station offline — permitted from `ONLINE` — cancels every `BOOKED` reservation whose `start_at` lies in the future and credits each such reservation's `fee_cents` back to its holder's wallet, conserving the wallet across the book-and-refund pair. Returning a station to service flips `OFFLINE` back to `ONLINE`.

A holder books a charging reservation by naming the `station_id`, their `holder_id`, a `slot_index` identifying the bay (valid values run from 0 to `slot_count` minus 1), and the window's `start_at` and `end_at`. The station must be `ONLINE`, or the booking is rejected with `ERR_STATION_OFFLINE` (HTTP 409). The fee charged at booking is the reservation's duration in minutes — any fractional minute rounded up — multiplied by the station's `rate_cents_per_min`, subject to a minimum charge of 200 cents; the computed `fee_cents` is debited from the holder's wallet immediately, and a balance below the fee (equality is sufficient) is rejected with `ERR_INSUFFICIENT_FUNDS`. The booking must also respect the buffered closed-interval rule of §2.10 against other `BOOKED` reservations on the same station and bay. The holder may cancel a `BOOKED` reservation before its `start_at` for a full refund of `fee_cents` to the wallet; once the clock moves past `end_at` the reservation completes (`BOOKED` → `COMPLETED`). `CANCELLED` and `COMPLETED` are terminal.

The shared fleet extends the infrastructure. A `CommunityAdmin` adds fleet vehicles with a `community_id`, a home `station_id`, and a display `label`; each starts `AVAILABLE`. A holder books a dispatch by naming the `vehicle_id`, their `holder_id`, and the shift window `shift_start` and `shift_end`; the holder must be `ELIGIBLE` (otherwise `ERR_HOLDER_NOT_ELIGIBLE`), and the closed-window overlap rule of §2.10 applies per vehicle. The dispatch starts `BOOKED`, with `returned_at` null until the vehicle is actually returned and `late_fine_cents` at zero unless a late return computes one.

Checkout is performed by the holder at or after `shift_start` and requires the vehicle to be `AVAILABLE` — if it is not, the attempt is rejected with `ERR_FLEET_UNAVAILABLE` (HTTP 409). A successful checkout moves the dispatch `BOOKED` → `CHECKED_OUT`, flips the vehicle `AVAILABLE` → `CHECKED_OUT`, and raises the community's `checked_out_count` by 1. If the clock moves past `shift_end` while the vehicle is still out, the dispatch flips to `OVERDUE`. The holder returns the vehicle from either `CHECKED_OUT` or `OVERDUE`: the dispatch records `returned_at` at the return instant and moves to `RETURNED` (terminal), the vehicle flips back to `AVAILABLE`, the community's `checked_out_count` drops by 1, and when the return is later than `shift_end` a late fine is computed — the number of days late with any partial day rounded up, multiplied by 500 cents — and recorded in `late_fine_cents` and debited from the holder's wallet. A return whose computed fine exceeds the wallet balance is rejected with `ERR_INSUFFICIENT_FUNDS`. A dispatch may instead be cancelled while `BOOKED` and before its `shift_start`; `CANCELLED` is terminal.

Fleet upkeep is administrative. A `CommunityAdmin` may move an `AVAILABLE` vehicle to `MAINTENANCE`, which cancels every `BOOKED` dispatch naming that vehicle whose `shift_start` lies in the future; moving it back from `MAINTENANCE` to `AVAILABLE` restores it for booking.

### 3.9. Violations, Points, and Enforcement Cascades

An `EnforcementOfficer` files a citation by naming the cited `holder_id`, an optional `registration_id` — null for holder-level citations not tied to a specific registration — a `violation_code`, the `points_assessed` (an integer from 1 to 12), a `fine_cents` amount (zero or more; informational only, never auto-debited), and the `occurred_at` instant when the violation happened. The violation code is one of `UNDERAGE_DRIVER`, `UNREGISTERED_VEHICLE`, `EQUIPMENT_MISSING`, `OFF_ROUTE`, `PARKING_VIOLATION`, or `UNINSURED_OPERATION`. A new citation starts `FILED`.

Adjudication has two outcomes. Upholding moves a `FILED` violation to `UPHELD` and triggers the standing recomputation: the holder's `points_balance` becomes the sum of `points_assessed` over all of the holder's violations currently in `UPHELD` status whose `occurred_at` lies within the trailing 730 days of now, the boundary included. Standing follows fixed thresholds — `BARRED` at 12 points or more (exactly 12 is `BARRED`), `PROBATION` at 4 through 11 points, and `GOOD_STANDING` at 3 or fewer — and the holder's `compliance_status` is rewritten accordingly. When this recomputation flips a holder into `BARRED`, the cascade of §2.11 fires: every `ACTIVE` registration belonging to the holder flips to `SUSPENDED`, and each such suspension revokes its `ACTIVE` route passes. Dismissing moves a violation from either `FILED` or `UPHELD` to `DISMISSED` — dismissing an `UPHELD` violation is the appeal path — and when the dismissed violation had been `UPHELD`, the holder's `points_balance` and `compliance_status` are recomputed downward. A dismissal never reinstates registrations on its own: holders who drop out of `BARRED` must have each suspended registration reinstated individually. Both `UPHELD` and `DISMISSED` are terminal states for the violation itself.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that modify an existing resource — including all state-transition actions, deposits, cancellations, and clock advances — return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/communities` | Create a community program | PlatformAdmin |
| GET | `/api/communities/{id}` | Read a community | PlatformAdmin, CommunityAdmin, Inspector, EnforcementOfficer, PermitHolder |
| PATCH | `/api/communities/{id}` | Update community configuration (OCC-guarded) | PlatformAdmin |
| GET | `/api/communities` | List communities | PlatformAdmin, CommunityAdmin |
| POST | `/api/permit-holders` | Self-register a permit holder (starts PENDING_VERIFICATION, GOOD_STANDING, 0 points, 0 wallet) | Anonymous, CommunityAdmin |
| GET | `/api/permit-holders/{id}` | Read a permit holder | PlatformAdmin, CommunityAdmin, Inspector, EnforcementOfficer, PermitHolder |
| GET | `/api/permit-holders` | List permit holders, optionally filtered by community | PlatformAdmin, CommunityAdmin, EnforcementOfficer |
| POST | `/api/permit-holders/{id}/verify-eligibility` | Verify driver age and license class; PENDING_VERIFICATION → ELIGIBLE | CommunityAdmin |
| POST | `/api/permit-holders/{id}/suspend` | Suspend the eligibility dimension (ELIGIBLE → SUSPENDED); compliance untouched | CommunityAdmin |
| POST | `/api/permit-holders/{id}/reinstate` | Reinstate the eligibility dimension (SUSPENDED → ELIGIBLE) | CommunityAdmin |
| POST | `/api/permit-holders/{id}/revoke` | Revoke eligibility; cascades registrations and their ACTIVE route passes to REVOKED | CommunityAdmin |
| POST | `/api/permit-holders/{id}/wallet/deposits` | Deposit funds into the holder wallet (OCC-guarded) | PermitHolder |
| POST | `/api/vehicles` | Register a vehicle with declared equipment; equipment_count computed | PermitHolder |
| GET | `/api/vehicles/{id}` | Read a vehicle | PlatformAdmin, CommunityAdmin, Inspector, EnforcementOfficer, PermitHolder |
| GET | `/api/vehicles` | List vehicles, optionally filtered by holder | PlatformAdmin, CommunityAdmin, Inspector, EnforcementOfficer, PermitHolder |
| POST | `/api/vehicles/{id}/retire` | Retire a vehicle with no non-terminal registrations | PermitHolder |
| POST | `/api/registrations` | Create a DRAFT annual registration with a provisional fee | PermitHolder |
| GET | `/api/registrations/{id}` | Read a registration | PlatformAdmin, CommunityAdmin, Inspector, EnforcementOfficer, PermitHolder |
| GET | `/api/registrations` | List registrations, optionally filtered by vehicle or holder | PlatformAdmin, CommunityAdmin, Inspector, EnforcementOfficer, PermitHolder |
| POST | `/api/registrations/{id}/activate` | Activate a DRAFT registration; debits total_due_cents | PermitHolder |
| POST | `/api/registrations/{id}/renew` | Open renewal inside the window (from ACTIVE) or grace period (from EXPIRED) | PermitHolder |
| POST | `/api/registrations/{id}/finalize-renewal` | Audit renewal: score at least 70 activates and debits; below 70 suspends | CommunityAdmin |
| POST | `/api/registrations/{id}/suspend` | Manually suspend an ACTIVE registration; revokes its ACTIVE route passes | CommunityAdmin |
| POST | `/api/registrations/{id}/reinstate` | Reinstate a SUSPENDED registration | CommunityAdmin |
| POST | `/api/registrations/{id}/revoke` | Revoke a non-DRAFT registration (terminal); revokes its ACTIVE route passes | EnforcementOfficer |
| POST | `/api/inspections` | Schedule an inspection for a registration | Inspector |
| GET | `/api/inspections/{id}` | Read an inspection | PlatformAdmin, CommunityAdmin, Inspector, EnforcementOfficer, PermitHolder |
| GET | `/api/inspections` | List inspections, optionally filtered by registration | PlatformAdmin, CommunityAdmin, Inspector, EnforcementOfficer, PermitHolder |
| POST | `/api/inspections/{id}/finalize` | Record component scores; computes total_score and applies pass/fail side effects | Inspector |
| POST | `/api/insurance-policies` | Document an insurance policy meeting the community minimum | PermitHolder |
| GET | `/api/insurance-policies/{id}` | Read a policy | PlatformAdmin, CommunityAdmin, Inspector, EnforcementOfficer, PermitHolder |
| GET | `/api/insurance-policies` | List policies, optionally filtered by holder or vehicle | PlatformAdmin, CommunityAdmin, Inspector, EnforcementOfficer, PermitHolder |
| POST | `/api/insurance-policies/{id}/cancel` | Cancel an ACTIVE policy | PermitHolder |
| POST | `/api/routes` | Designate a street or path route | CommunityAdmin |
| GET | `/api/routes/{id}` | Read a route | PlatformAdmin, CommunityAdmin, Inspector, EnforcementOfficer, PermitHolder |
| GET | `/api/routes` | List routes, optionally filtered by community | PlatformAdmin, CommunityAdmin, Inspector, EnforcementOfficer, PermitHolder |
| POST | `/api/routes/{id}/decommission` | Decommission a route; revokes its ACTIVE route passes | CommunityAdmin |
| POST | `/api/route-passes` | Book a half-open pass window for an ACTIVE registration on a DESIGNATED route | PermitHolder |
| GET | `/api/route-passes/{id}` | Read a route pass | PlatformAdmin, CommunityAdmin, Inspector, EnforcementOfficer, PermitHolder |
| GET | `/api/route-passes` | List route passes, optionally filtered by route, registration, or holder | PlatformAdmin, CommunityAdmin, Inspector, EnforcementOfficer, PermitHolder |
| POST | `/api/route-passes/{id}/cancel` | Cancel an ACTIVE pass before its window begins | PermitHolder |
| POST | `/api/charging-stations` | Create a charging station | CommunityAdmin |
| GET | `/api/charging-stations/{id}` | Read a station | PlatformAdmin, CommunityAdmin, Inspector, EnforcementOfficer, PermitHolder |
| GET | `/api/charging-stations` | List stations, optionally filtered by community | PlatformAdmin, CommunityAdmin, Inspector, EnforcementOfficer, PermitHolder |
| POST | `/api/charging-stations/{id}/set-offline` | Take a station offline; future BOOKED reservations cancelled and refunded | CommunityAdmin |
| POST | `/api/charging-stations/{id}/set-online` | Return a station to service | CommunityAdmin |
| POST | `/api/charging-reservations` | Book a charging slot; debits fee_cents from the holder wallet | PermitHolder |
| GET | `/api/charging-reservations/{id}` | Read a reservation | PlatformAdmin, CommunityAdmin, Inspector, EnforcementOfficer, PermitHolder |
| GET | `/api/charging-reservations` | List reservations, optionally filtered by station or holder | PlatformAdmin, CommunityAdmin, Inspector, EnforcementOfficer, PermitHolder |
| POST | `/api/charging-reservations/{id}/cancel` | Cancel a BOOKED reservation before start; full refund | PermitHolder |
| POST | `/api/fleet-vehicles` | Add a shared fleet vehicle | CommunityAdmin |
| GET | `/api/fleet-vehicles/{id}` | Read a fleet vehicle | PlatformAdmin, CommunityAdmin, Inspector, EnforcementOfficer, PermitHolder |
| GET | `/api/fleet-vehicles` | List fleet vehicles, optionally filtered by community or station | PlatformAdmin, CommunityAdmin, Inspector, EnforcementOfficer, PermitHolder |
| POST | `/api/fleet-vehicles/{id}/set-maintenance` | Move an AVAILABLE vehicle to MAINTENANCE; future BOOKED dispatches cancelled | CommunityAdmin |
| POST | `/api/fleet-vehicles/{id}/set-available` | Return a MAINTENANCE vehicle to AVAILABLE | CommunityAdmin |
| POST | `/api/fleet-dispatches` | Book a dispatch shift window for a fleet vehicle; holder must be ELIGIBLE | PermitHolder |
| GET | `/api/fleet-dispatches/{id}` | Read a dispatch | PlatformAdmin, CommunityAdmin, Inspector, EnforcementOfficer, PermitHolder |
| GET | `/api/fleet-dispatches` | List dispatches, optionally filtered by vehicle or holder | PlatformAdmin, CommunityAdmin, Inspector, EnforcementOfficer, PermitHolder |
| POST | `/api/fleet-dispatches/{id}/checkout` | Check out the vehicle at or after shift_start | PermitHolder |
| POST | `/api/fleet-dispatches/{id}/return` | Return the vehicle; computes and debits the late fine when past shift_end | PermitHolder |
| POST | `/api/fleet-dispatches/{id}/cancel` | Cancel a BOOKED dispatch before shift_start | PermitHolder |
| POST | `/api/violations` | File a violation citation | EnforcementOfficer |
| GET | `/api/violations/{id}` | Read a violation | PlatformAdmin, CommunityAdmin, EnforcementOfficer, PermitHolder |
| GET | `/api/violations` | List violations, optionally filtered by holder or registration | PlatformAdmin, CommunityAdmin, EnforcementOfficer |
| POST | `/api/violations/{id}/uphold` | Uphold a FILED violation; recomputes points and standing; BARRED flip cascades | EnforcementOfficer |
| POST | `/api/violations/{id}/dismiss` | Dismiss a FILED or UPHELD violation; recomputes points and standing downward | EnforcementOfficer |
| POST | `/_clock/set_current_utc` | Set the logical clock; evaluates all time-driven transitions | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_UNDERAGE_DRIVER` | 422 Unprocessable Entity |
| `ERR_LICENSE_CLASS_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_EQUIPMENT_MINIMUM` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_REGISTRATION` | 409 Conflict |
| `ERR_INSPECTION_NOT_PASSED` | 422 Unprocessable Entity |
| `ERR_INSURANCE_MISSING` | 422 Unprocessable Entity |
| `ERR_INSURANCE_COVERAGE_LOW` | 422 Unprocessable Entity |
| `ERR_HOLDER_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_HOLDER_BARRED` | 422 Unprocessable Entity |
| `ERR_REGISTRATION_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_ROUTE_NOT_DESIGNATED` | 422 Unprocessable Entity |
| `ERR_ROUTE_VEHICLE_CLASS` | 422 Unprocessable Entity |
| `ERR_ROUTE_PASS_OVERLAP` | 409 Conflict |
| `ERR_CHARGING_OVERLAP` | 409 Conflict |
| `ERR_DISPATCH_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_STATION_OFFLINE` | 409 Conflict |
| `ERR_INSUFFICIENT_FUNDS` | 402 Payment Required |
| `ERR_RENEWAL_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_FLEET_UNAVAILABLE` | 409 Conflict |

# Living History & Reenactment Event Management API — Product Requirements Document

## 1. Introduction

Running a living history or reenactment event means holding two obligations in constant tension: the public expects a convincing spectacle — period-correct garb, black-powder demonstrations, bustling sutler row — while the organizer carries legal and safety duties that would shut the show down in an afternoon if mismanaged. Landowner permission and liability insurance must be in force before tickets can be advertised; every musket, sword, cannon, and camp flame must pass inspection before its owner may muster in; minors may only take the field under documented adult supervision; and a single lightning storm or fire-ban notice must be able to ripple through the entire site, cancelling open-flame programs and tightening posture without a clerk chasing paper forms.

This document specifies an API that manages that entire arc for a single-event organizer: event configuration and commercial terms, landowner and insurance agreements, reenactment unit registration and vetting, participant authenticity review and gate check-in, equipment declaration and safety inspection with segregation of duties, site layout and ground allocation, the program of public demonstrations, spectator ticketing with early-bird pricing and refunds, parking lot management, sutler (vendor) applications through post-event fee settlement, and weather/fire/security contingency operations including full event cancellation. The system is posture-driven: the event's lifecycle posture and a restriction level derived from open contingency alerts gate nearly every child operation, and temporal windows — program slots, ground allocations, inspection appointments, agreement in-force periods — are validated with explicit boundary semantics throughout.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the caller's operational capacity. The system recognizes exactly seven roles, spelled precisely as follows: `EventOrganizer`, `AuthenticityOfficer`, `SafetyOfficer`, `UnitCommander`, `Participant`, `Vendor`, and `Spectator`. A request whose `X-User-Role` does not name one of these roles, or that omits `X-User-ID` on any non-creation call where an identity is required, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Authorization is then per-endpoint: a caller whose role is not listed for the endpoint, or who fails an entity-backed ownership check, is rejected with `ERR_FORBIDDEN` (HTTP 403).

The relationship between `X-User-ID` and persisted entities differs by role, and is fixed as follows:

- When `X-User-Role` is `EventOrganizer`, `AuthenticityOfficer`, or `SafetyOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `recorded_by_user_id` on an inspection when a safety officer records an outcome, or as `waived_by_user_id` when one waives a failure — but never compares it to any entity's `id`.
- When `X-User-Role` is `UnitCommander`, `X-User-ID` is the `id` of the acting Unit; ownership checks on any resource that references a Unit compare the resource's foreign-key field to `X-User-ID`. A unit commander acts only on its own unit and on that unit's participants and their equipment. The binding is established by bootstrap at unit creation: the registering caller's `X-User-ID` becomes the created unit's `id`.
- When `X-User-Role` is `Participant`, `X-User-ID` is the `id` of the acting Participant; ownership checks compare the participant reference to `X-User-ID`, and a participant acts only on itself and its own equipment. The binding is established by bootstrap at self-registration: the self-registering caller's `X-User-ID` becomes the created participant's `id`.
- When `X-User-Role` is `Vendor`, `X-User-ID` anchors to the applying vendor record's `owner_user_id`; ownership checks on a vendor resource compare `owner_user_id` to `X-User-ID`. The anchor is recorded from the caller's `X-User-ID` at application time; when the application arrives without an `X-User-ID`, the created vendor's own `id` becomes the self-anchor instead.
- When `X-User-Role` is `Spectator`, `X-User-ID` is an opaque buyer identifier not tied to any persisted account entity; the server stores it as `buyer_user_id` on each ticket order the spectator creates, and ownership checks on orders and parking passes compare that stored `buyer_user_id` to `X-User-ID`.

On creation endpoints the `X-User-ID` header may be omitted; where a bootstrap rule would have consumed it — unit registration or participant self-registration — the server instead mints a random UUID as the new resource's `id`.

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

A request that matches no route is rejected with `ERR_NOT_FOUND` (HTTP 404), and a matched path called with an unsupported method is rejected with `ERR_METHOD_NOT_ALLOWED` (HTTP 405); both use this same envelope.

---

### 2.3. Pagination

List endpoints are paginated through query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. A `limit` that is not an integer or falls outside [1, 100], or an `offset` that is not an integer or is negative, is rejected with `ERR_VALIDATION`. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties on `created_at` — common under the frozen logical clock — broken by creation (insertion) order. The `meta` object of list responses carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Mutation Semantics

Every resource in the system — events, agreements, units, participants, equipment items, inspections, site areas, allocations, program slots, ticket orders, parking passes, vendors, and contingency alerts — carries a uniform set of system-managed properties:

- `id` (string): a server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification; at creation it equals `created_at`.
- `version` (integer): a system-managed mutation counter, starting at 1 at creation.

Every state transition and every mutating write described in §3 increments the affected resource's `version` by exactly one and refreshes its `updated_at`. This holds equally for client-invoked transitions and for system-driven cascade transitions: when a unit suspension withdraws a participant, withdraws that participant's equipment, and cancels the equipment's scheduled inspections, each of those resources has its own `version` incremented and `updated_at` refreshed.

### 2.5. The Logical Clock

The server maintains a logical clock that governs all time-dependent behavior. At startup the logical time is fixed at 2026-05-01T00:00:00Z and must never fall back to wall-clock time. Every timestamp the system stamps — `signed_at`, `checked_in_at`, `paid_at`, `refunded_at`, `cancelled_at`, `resolved_at`, `insurance_uploaded_at` — reads this logical clock, and every timestamp comparison — early-bird cutoff eligibility, the sutler insurance deadline, agreement in-force windows, refund pro-rating — is evaluated against it. For test-driving purposes, an organizer-only capability sets the logical clock: the request carries a `to_iso8601` instant (ISO 8601 UTC), and the response echoes the new logical time as `current_utc`.

### 2.6. Event Posture and the Restriction Level

An event's `event_posture` cycles through `PLANNING`, `REGISTRATION_OPEN`, `PUBLISHED`, `EVENT_OPEN`, `RESTRICTED`, and the terminal states `COMPLETED` and `CANCELLED`. The loop between `EVENT_OPEN` and `RESTRICTED` is cyclic and may be traversed repeatedly as conditions change. Posture is the system's primary gate: nearly every child operation — unit and participant registration, vetting support, check-in, slot confirmation, ticket sales, vendor contracting, settlement — is permitted only in named postures, and an operation attempted in a posture that does not permit it is rejected with `ERR_INVALID_EVENT_POSTURE` (HTTP 409). The precise posture set for each operation is stated in §3 alongside the workflow it guards.

Independent of posture, every event carries a computed `restriction_level` of `GREEN`, `YELLOW`, or `RED`, derived from the event's currently `OPEN` contingency alerts: the level is `RED` when any open alert has severity `RED_FLAG`, otherwise `YELLOW` when any open alert has severity `WATCH`, otherwise `GREEN`. An `ADVISORY` alert never influences the level. The level is recomputed whenever an alert is raised or resolved.

### 2.7. Money, Integer Cents, and Rounding

All monetary amounts are represented as integer cents — prices, fees, coverage amounts, quotes, charges, refunds, and balances alike. Where a calculation produces a fractional cent, the result is rounded half-up to whole cents. Two rounding disciplines matter and must not be interchanged: ticket pricing rounds each line half-up before lines are summed, and the flat per-order service fee is added after the sum; refund and vendor-fee calculations round half-up once at the point stated in their formulas. The early-bird boundary is inclusive: a pricing timestamp exactly equal to the cutoff qualifies for the discount. The sutler late-insurance boundary is strict: a certificate uploaded exactly at the deadline does not incur the surcharge.

### 2.8. Optimistic Concurrency Control

Exactly two write operations are guarded by optimistic concurrency control, both against the Event: updating an event's mutable settings, and submitting a new agreement under an event. Each requires a non-optional `expected_event_version` field in the request body, carrying the event `version` the client last observed. If that value does not match the event's current `version` — for example, because another organizer has since patched the event or submitted an agreement, both of which advance the event's version — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no change is applied. Only a present integer value is compared for staleness; a missing or non-integer `expected_event_version` is a request-body failure rejected with `ERR_VALIDATION`, surfacing only after the posture check per §2.9 — so a stale integer version wins over a posture error, while a missing field loses to one. No endpoint other than these two accepts a version field.

### 2.9. Validation Order and Referential Existence

When several checks could reject the same request, the server evaluates them in a fixed category order, and a request failing an earlier category never surfaces a later category's error. The order is: first authentication and role/ownership authorization (§2.1); second, referential existence of every identifier appearing in the path or body; third, the optimistic-concurrency staleness check; fourth, state and posture fitness; fifth, business safety gates (uninspected equipment, supervisor rules and ratios, open-flame restriction, open red-flag alerts, segregation of duties); sixth, request-body shape and business constraints (missing or malformed fields, unit-in-event, overlap, allocation party, area-kind fitness); seventh, temporal ranges and event-window containment; eighth, agreement-in-force referential checks; and ninth, fiscal and capacity checks (insurance sufficiency, vendor balance, parking and area capacity).

The existence family maps each unresolved reference to its own error: an unresolvable event reference yields `ERR_EVENT_NOT_FOUND`; a unit, `ERR_UNIT_NOT_FOUND`; a participant or a non-null supervisor reference, `ERR_PARTICIPANT_NOT_FOUND`; an equipment item, `ERR_EQUIPMENT_NOT_FOUND`; an inspection, `ERR_INSPECTION_NOT_FOUND`; a site area, `ERR_AREA_NOT_FOUND`; a program slot, `ERR_SLOT_NOT_FOUND`; a ticket order, `ERR_ORDER_NOT_FOUND`; a parking pass, `ERR_PASS_NOT_FOUND`; a vendor, `ERR_VENDOR_NOT_FOUND`; an agreement, `ERR_AGREEMENT_NOT_FOUND`; a contingency alert, `ERR_ALERT_NOT_FOUND`; and an allocation, `ERR_ALLOCATION_NOT_FOUND`. All are HTTP 404. Where a URL nests one resource beneath another, identifiers are validated left to right, and the first identifier that fails to resolve determines the error returned.

### 2.10. Cascading Consistency

Parent-level decisions propagate downward without requiring separate client calls, and every hop of every cascade performs the version and timestamp mutation described in §2.4. Three cascades exist. Suspending a unit runs a depth-three cascade: unit to its participants, participants to their equipment, equipment to its scheduled inspections. Withdrawing a participant runs a depth-two cascade over that participant's equipment and inspections. Cancelling an event runs the full-site cascade: orders refunded or cancelled, parking passes voided, program slots cancelled, allocations released, vendors revoked, and open alerts resolved. Derived tallies — a site area's `allocated_units`, the event-level and unit-level `approved_combatant_count`, and the event's `restriction_level` — are recomputed by the server whenever the underlying records change, and never accepted as client input.

## 3. Business Logic & Workflows

### 3.1. Configuring the Event and Its Commercial Terms

An `EventOrganizer` founds an event by supplying its public identity — `name` and `site_name` — together with `event_starts_at` and `event_ends_at`, the first and last scheduled moments of the public window. The same creation call fixes the event's commercial terms: the four list prices `adult_day_price_cents`, `child_day_price_cents`, `adult_weekend_price_cents`, and `child_weekend_price_cents` (child tickets are for visitors under thirteen); the early-bird terms `early_bird_pct`, a discount fraction such as 0.20, and `early_bird_cutoff_at`, the inclusive eligibility boundary; the flat per-order `service_fee_cents`, always added after line items are summed and never discounted; and `refund_retain_pct`, the fraction of a paid order retained when a patron voluntarily withdraws. Legal and safety parameters travel with the same record: `required_liability_cents`, the minimum liability coverage the event must evidence before it may publish; and `max_minor_per_adult`, the supervision ratio capping minors per checked-in adult within a unit, which defaults to 4 when omitted. Sutler-row economics are likewise fixed at creation: `vendor_frontage_rate_cents` per frontage foot per day, `vendor_multi_day_discount_pct` for long bookings, `vendor_min_fee_cents` as the booth-fee floor, `vendor_late_insurance_surcharge_cents`, and `vendor_insurance_deadline_at`. All of these `*_cents` fields must be non-negative integers; `early_bird_pct`, `refund_retain_pct`, and `vendor_multi_day_discount_pct` must be numbers between 0 and 1 inclusive; and `max_minor_per_adult` must be a non-negative integer. No coherence check between `event_starts_at` and `event_ends_at` is applied at creation. A new event begins in `PLANNING` posture with `restriction_level` `GREEN`, an `approved_combatant_count` of zero, and `cancelled_at` null.

While the event remains in `PLANNING` or `REGISTRATION_OPEN`, the organizer may update its mutable settings — any of `name`, `site_name`, `event_starts_at`, `event_ends_at`, `required_liability_cents`, and `max_minor_per_adult` — via a request that must also carry `expected_event_version` per §2.8; the update bumps the event's `version`. Mutable fields absent from the payload or set to null are left unchanged, and any other payload fields are ignored. Outside those two postures the update is rejected with `ERR_INVALID_EVENT_POSTURE`. When configuration is complete, the organizer opens registration, moving the event `PLANNING → REGISTRATION_OPEN`, which admits unit, participant, and vendor registrations under §3.3 and §3.8.

### 3.2. Landowner and Insurance Agreements

Before an event may be published, two documentary obligations must be met, and both are modeled as Agreement resources. An organizer submits an agreement by naming the `agreement_type` — `LANDOWNER_USE` for the landowner's permission to use the ground, or `INSURANCE_LIABILITY` for liability cover — together with a `document_ref` pointing at the external document and the in-force window `effective_from` through `effective_until`, both inclusive. The window must be coherent: `effective_from` on or before `effective_until`, else the submission fails with `ERR_INVALID_TIME_RANGE`. `coverage_amount_cents` is required if and only if the type is `INSURANCE_LIABILITY` — absent for a liability agreement, or present for a landowner agreement, is a body-shape failure rejected with `ERR_VALIDATION` — and is otherwise null. Submission is permitted in any non-terminal posture, and is OCC-guarded per §2.8: the request must carry `expected_event_version` matching the event's current version, or it is rejected with `ERR_STALE_VERSION`.

A new agreement begins in `SUBMITTED` status. Submitting one automatically supersedes every prior agreement of the same `agreement_type` for the same event: any such agreement in `SUBMITTED` or `SIGNED` moves to `SUPERSEDED`. Because agreement activity changes the event's documentary state, submitting an agreement also increments the event's `version` by one — which is precisely what makes a second writer's stale `expected_event_version` detectable. Signing is an organizer action valid only from `SUBMITTED` (any other status is rejected with `ERR_INVALID_AGREEMENT_STATUS`); it records the payload's `signer_name` and stamps `signed_at`, moving the agreement to `SIGNED`. An agreement is in force when its status is `SIGNED` and the logical now falls within its window, `effective_from` on or before now and now on or before `effective_until`. The event's agreement listing returns agreements of every status, including `SUPERSEDED`, in creation order.

Publication — `REGISTRATION_OPEN → PUBLISHED` — enforces both obligations. First, a `SIGNED` `LANDOWNER_USE` agreement must exist whose window covers the entire event: `effective_from` on or before `event_starts_at` and `effective_until` on or after `event_ends_at`; without one, publication fails with `ERR_AGREEMENT_NOT_IN_FORCE`. Second, a `SIGNED` `INSURANCE_LIABILITY` agreement must exist whose window likewise covers the event and whose `coverage_amount_cents` is at least the event's `required_liability_cents`; otherwise publication fails with `ERR_INSURANCE_COVERAGE_INSUFFICIENT`. Both checks are referential-fiscal gates applied after state and posture have been validated, in the order given by §2.9.

### 3.3. Units, Participants, and the Muster

Reenactors organize into units. A `UnitCommander` registers a unit by supplying `event_id`, a roster `name`, the `unit_type` (`MILITARY`, `CIVILIAN`, or `ARTILLERY`), the `portrayal_name` of the historical unit portrayed, and optionally `headcount_estimate` (a non-negative integer, default 0). Registration requires the event to be in `REGISTRATION_OPEN` or `PUBLISHED` posture, and bootstraps the commander's identity per §2.1: the caller's `X-User-ID` becomes the created unit's `id`. A unit begins `SUBMITTED`. The organizer vets it with a `decision` of `APPROVE` or `REJECT` and optional `notes`, which are recorded as the unit's `vet_notes`; approval moves `SUBMITTED → APPROVED`, rejection moves `SUBMITTED → REJECTED` (terminal). Vetting is valid from `SUBMITTED` or `SUSPENDED`, and suspension is valid only from `APPROVED`; any other from-state is rejected with `ERR_INVALID_UNIT_STATUS`.

Suspending a unit is the system's depth-three cascade. The unit moves `APPROVED → SUSPENDED`, and then, hop by hop: every participant of the unit in `SUBMITTED`, `CHANGES_REQUESTED`, or `VETTED` status moves to `WITHDRAWN`; for each participant so withdrawn, every equipment item in `DECLARED`, `INSPECTION_DUE`, or `FAILED` moves to `WITHDRAWN`; and for each item so withdrawn, every `SCHEDULED` inspection moves to `CANCELLED`. A suspended unit may be reinstated by vetting it with `decision` `APPROVE` (`SUSPENDED → APPROVED`), but participants withdrawn by the suspension cascade are not restored — each must re-register or be re-vetted on its own merits; vetting a `SUSPENDED` unit with `decision` `REJECT` is rejected with `ERR_INVALID_UNIT_STATUS`. The optional `reason` payload accompanies a suspension but is not persisted on any record.

Individuals register with `full_name`, `age_at_event` (their age in years on the event's first day, a non-negative integer), and `impression_class` (`COMBATANT`, `CIVILIAN`, or `ARTILLERY_CREW`), plus an optional `persona_description` for the authenticity reviewers (defaulting to an empty string) and an optional `supervisor_participant_id`. An optional `unit_id` affiliates the participant with a unit; its absence (null) marks an independent reenactor. Three role paths exist: a `UnitCommander` registers members of its own unit, a `Participant`-role caller self-registers as an independent (bootstrapping `X-User-ID` to the new participant's `id`), and an `EventOrganizer` may register anyone. Registration requires posture `REGISTRATION_OPEN` or `PUBLISHED`. Referential checks follow §2.9: a non-null `unit_id` must resolve (`ERR_UNIT_NOT_FOUND`) and must belong to the same event as the participant's `event_id` (`ERR_UNIT_NOT_IN_EVENT`); a non-null `supervisor_participant_id` must resolve (`ERR_PARTICIPANT_NOT_FOUND`) and must not equal the participant's own id (`ERR_VALIDATION`). The system computes `is_minor`, true exactly when `age_at_event` is under 18. A new participant begins in `DRAFT`.

Submission moves a participant `DRAFT → SUBMITTED`, and resubmission after requested changes moves `CHANGES_REQUESTED → SUBMITTED`; both are performed by the unit's commander or the participant personally, both require the affiliated unit — when `unit_id` is non-null — to be `APPROVED` (`ERR_INVALID_UNIT_STATUS` otherwise; a `SUSPENDED` unit blocks both submission and check-in), and any other from-state is rejected with `ERR_INVALID_PARTICIPANT_STATUS`. Authenticity vetting belongs to the `AuthenticityOfficer` alone, acting on a `SUBMITTED` record with a `decision`: `APPROVE` moves to `VETTED`, `REQUEST_CHANGES` moves to `CHANGES_REQUESTED` (opening the resubmission loop), and `REJECT` moves to `REJECTED`, terminal. Each decision carries optional `notes` recorded as the participant's `vet_notes`.

Two derived tallies track fighting strength. The event-level `approved_combatant_count` counts participants of the event whose status is `VETTED` or `CHECKED_IN`, whose `impression_class` is `COMBATANT`, and whose unit — when they have one — is `APPROVED`; participants of a suspended unit therefore drop out of the event-level count while the suspension stands. A unit's own `approved_combatant_count` counts its participants in `VETTED` or `CHECKED_IN` with `impression_class` `COMBATANT`. Records in `DRAFT`, `SUBMITTED`, `CHANGES_REQUESTED`, `REJECTED`, or `WITHDRAWN` never count. Both tallies are recomputed on vet approval, on check-in, on withdrawal, and on unit suspension.

Mustering in — `VETTED → CHECKED_IN` — is performed by an `EventOrganizer` or `SafetyOfficer` and is the most heavily gated transition in the system. The event must be in `EVENT_OPEN` posture (`ERR_INVALID_EVENT_POSTURE`); the participant's unit, when affiliated, must be `APPROVED` (`ERR_INVALID_UNIT_STATUS`); the participant must be in `VETTED` (`ERR_INVALID_PARTICIPANT_STATUS`); and no equipment item of the participant with `item_type` `FIREARM`, `EDGED`, `CANNON`, or `CAMP_FLAME` may sit in `DECLARED`, `INSPECTION_DUE`, or `FAILED` — such an item blocks check-in with `ERR_UNINSPECTED_EQUIPMENT`, while `TENTAGE` and `OTHER` items never do. For a minor, three further gates apply in sequence: `supervisor_participant_id` must be set, else `ERR_SUPERVISOR_REQUIRED`; the named supervisor must be an adult (`age_at_event` at least 18), must belong to the same unit as the minor, and must already be `CHECKED_IN`, else `ERR_SUPERVISOR_INELIGIBLE`; and the unit's supervision ratio must admit one more minor — the number of the unit's already checked-in minors plus one must be at most the event's `max_minor_per_adult` multiplied by the number of the unit's already checked-in adults, an inclusive boundary — else `ERR_SUPERVISION_RATIO_EXCEEDED`. Both ratio counts are taken at check-in time, after the supervisor's own check-in, and span the same unit only; an independent minor (null `unit_id`) is governed by the supervisor gates and not by the ratio. A successful muster stamps `checked_in_at` and recomputes both combatant tallies.

Withdrawal moves a participant from any non-terminal status to `WITHDRAWN`; a record already terminal is rejected with `ERR_INVALID_PARTICIPANT_STATUS`. The participant themself, their unit commander, or an organizer may withdraw a record, with an optional `reason` (accepted but not persisted). Withdrawing from `DRAFT`, `SUBMITTED`, `CHANGES_REQUESTED`, or `VETTED` also withdraws the participant's equipment in `DECLARED`, `INSPECTION_DUE`, or `FAILED` and cancels those items' `SCHEDULED` inspections; a mid-event departure from `CHECKED_IN` carries no equipment cascade but recomputes the combatant tallies. Participant listings support filtering by `unit_id`, `event_id`, `supervisor_participant_id`, and `status`, with `limit` and `offset` pagination. On the listing, a `UnitCommander` sees only participants of its own unit and a `Participant`-role caller only itself; a `unit_id` filter that does not resolve is rejected with `ERR_UNIT_NOT_FOUND`, while the other filters are applied as plain equality without referential validation.

### 3.4. Equipment Safety and the Inspection Pipeline

Every regulated item is declared before it is inspected. A participant, their unit commander, or an organizer declares an item with `participant_id`, `item_type` (`FIREARM`, `EDGED`, `CANNON`, `CAMP_FLAME`, `TENTAGE`, or `OTHER`), and a free-text `description` of make, pattern, and material. Declaration requires the owning participant to be neither `REJECTED` nor `WITHDRAWN` (`ERR_INVALID_PARTICIPANT_STATUS`). An item begins `DECLARED` with `failure_count` zero.

Inspection scheduling belongs to the `SafetyOfficer`. Scheduling supplies `scheduled_for` — the start of the item's fixed forty-five-minute window — and `inspection_kind`, either `SAFETY` or `AUTHENTICITY`. The item must be in `DECLARED`, `FAILED`, or `INSPECTION_DUE` (`ERR_INVALID_EQUIPMENT_STATUS` otherwise); scheduling from `DECLARED` or `FAILED` moves the item to `INSPECTION_DUE`, and scheduling while already `INSPECTION_DUE` stacks an additional inspection — an authenticity review after a safety review, for instance. Because inspections of the same item must not crowd one another, a conflict check applies: the new window, expanded by fifteen minutes on both sides, must not intersect any other `SCHEDULED` inspection window of the same equipment item, and for this buffered comparison touching counts as conflict. Consequently a new inspection beginning exactly fifteen minutes after an existing window's end is rejected with `ERR_INSPECTION_WINDOW_CONFLICT`, while one beginning sixteen minutes after is accepted.

Every inspection is bound to its subject through `equipment_item_id`, referencing the item under review. Recording an outcome likewise belongs to the `SafetyOfficer` and is valid only from `SCHEDULED` (`ERR_INVALID_INSPECTION_STATUS`). The recorder's `X-User-ID` is stamped as `recorded_by_user_id`. With `outcome` `PASS`, the inspection becomes `RECORDED_PASS`, the item moves `INSPECTION_DUE → PASSED`, and every other `SCHEDULED` inspection of the same item is cancelled. With `outcome` `FAIL`, the payload must carry `failure_reason` — its absence is `ERR_VALIDATION` — which is recorded verbatim; the inspection becomes `RECORDED_FAIL`; the item moves `INSPECTION_DUE → FAILED` and its `failure_count` is incremented by one, except that an increment bringing `failure_count` to two moves the item immediately to `BANNED` instead; and every other `SCHEDULED` inspection of the same item is cancelled.

A failed inspection may be set aside only under segregation of duties. Waiving is valid only from `RECORDED_FAIL` (`ERR_INVALID_INSPECTION_STATUS`), requires a `waiver_reason`, and — critically — the waiving officer's `X-User-ID` must differ from the inspection's `recorded_by_user_id`; the same officer who recorded the failure cannot waive it, and such an attempt is rejected with `ERR_SOD_SELF_WAIVER`. A successful waiver stamps `waived_by_user_id`, records the reason, moves the inspection to `WAIVED`, and moves the item `FAILED → WAIVED`.

An item may also be withdrawn outright by the participant, their commander, or an organizer from `DECLARED`, `INSPECTION_DUE`, or `FAILED` (`ERR_INVALID_EQUIPMENT_STATUS` otherwise). Withdrawing an `INSPECTION_DUE` item cancels its `SCHEDULED` inspections; withdrawing from `DECLARED` or `FAILED` has no such inspections outstanding. `PASSED`, `WAIVED`, `BANNED`, and `WITHDRAWN` are the item's terminal states.

### 3.5. Laying Out the Grounds: Site Areas and Allocations

The organizer subdivides the venue into site areas, each with an `area_name` (such as "Union Camp North" or "Lot B"), an `area_kind` of `CAMP`, `DEMO`, `PARKING`, `SUTLER`, or `SPECTATOR`, and a `capacity_units` (a non-negative integer) expressed in abstract units — tents, booth frontage blocks, or vehicle units depending on kind. Areas may be defined while the event is in `PLANNING`, `REGISTRATION_OPEN`, or `PUBLISHED`. An area begins `ACTIVE`; the organizer or a safety officer may close it, moving it to `CLOSED` (terminal). Each area exposes a computed `allocated_units`: for a `PARKING` area, the sum of `units_used` over its `ACTIVE` parking passes; for every other kind, the sum of `units` over its `ACTIVE` allocations. The area listing supports an `area_kind` filter.

Ground allocation places one occupying party on one area for a half-open occupation window. The organizer supplies `starts_at` and `ends_at` — the window runs from `starts_at` inclusive to `ends_at` exclusive — the `units` of capacity consumed (an integer of at least one), and exactly one of `unit_id` or `vendor_id`: naming neither, or both, is rejected with `ERR_ALLOCATION_PARTY_REQUIRED`. Allocation requires posture `REGISTRATION_OPEN`, `PUBLISHED`, or `EVENT_OPEN`; the area must resolve (`ERR_AREA_NOT_FOUND`), must be `ACTIVE` (`ERR_AREA_NOT_ACTIVE`), and must suit the party — a unit may occupy only `CAMP` ground and a vendor only `SUTLER` row, otherwise `ERR_AREA_KIND_MISMATCH`. The party must also be in good standing: a unit party must be `APPROVED` (`ERR_INVALID_UNIT_STATUS`) and a vendor party must be `CONTRACTED` (`ERR_INVALID_VENDOR_STATUS`). The window must be internally coherent — `starts_at` strictly before `ends_at`, else `ERR_INVALID_TIME_RANGE` — and must lie within the event window expanded by a twenty-four-hour setup and teardown allowance on each side: no earlier than twenty-four hours before `event_starts_at` and no later than twenty-four hours after `event_ends_at`, else `ERR_OUTSIDE_EVENT_WINDOW`. Two further business checks apply against the area's existing `ACTIVE` allocations: overlap — the new window conflicts when it begins before an existing window ends and that existing window begins before the new window ends, while merely touching endpoints are not a conflict, and a violation is `ERR_ALLOCATION_OVERLAP` — and capacity, where the area's `allocated_units` plus the requested `units` must not exceed `capacity_units` on an inclusive boundary (a request that exactly fills the area succeeds), else `ERR_AREA_CAPACITY_EXCEEDED`. Creating the allocation recomputes the area's `allocated_units`.

Releasing an allocation — an organizer action, or the system's during event cancellation — moves it `ACTIVE → RELEASED` and recomputes the area's `allocated_units`; releasing an allocation that is not `ACTIVE` is rejected with `ERR_VALIDATION`. The allocation listing filters by `site_area_id`, `unit_id`, or `vendor_id` with `limit` and `offset`.

### 3.6. The Program of Demonstrations

Public programming is built from program slots placed on demonstration ground. The organizer proposes a slot with a `title`, the `site_area_id` of its stage, and a half-open window `starts_at` to `ends_at`; `open_flame` flags programs involving open flame or black powder (default false), and `required_combatants` declares the minimum approved combatant strength needed to run it (a non-negative integer, default 0). Proposal requires posture `PUBLISHED` or `EVENT_OPEN`; the area must be `ACTIVE` (`ERR_AREA_NOT_ACTIVE`) and of kind `DEMO` (`ERR_AREA_KIND_MISMATCH`); the window must be coherent (`starts_at` strictly before `ends_at`, else `ERR_INVALID_TIME_RANGE`) and must lie entirely within the event's public window from `event_starts_at` to `event_ends_at` (else `ERR_OUTSIDE_EVENT_WINDOW`). Slots on the same area must not collide: the new window conflicts with an existing `PROPOSED` or `CONFIRMED` slot on that area when it begins before the existing slot ends and the existing slot begins before the new one ends; touching endpoints are permitted, and a true conflict is rejected with `ERR_SLOT_OVERLAP`. A new slot begins `PROPOSED`.

Confirmation is the organizer's commitment to run the program, valid only from `PROPOSED` (`ERR_INVALID_SLOT_STATUS`). Four gates apply: the area must still be `ACTIVE` (`ERR_AREA_NOT_ACTIVE`); when `open_flame` is true, the event's `restriction_level` must be `GREEN` — confirming flame under `YELLOW` or `RED` is rejected with `ERR_OPEN_FLAME_RESTRICTED`; `required_combatants` must not exceed the event's current `approved_combatant_count` (`ERR_VALIDATION`); and the event must be in `PUBLISHED` or `EVENT_OPEN` posture (`ERR_INVALID_EVENT_POSTURE`). Confirmation moves the slot `PROPOSED → CONFIRMED`.

A slot in `PROPOSED` or `CONFIRMED` may be cancelled by the organizer or a safety officer with an optional `reason`, recorded as `cancel_reason`; cancelling from any other status is `ERR_INVALID_SLOT_STATUS`. Cancellations also arrive from above: when the event is restricted, open-flame slots are cancelled with `cancel_reason` `CONTINGENCY`, and when the event is cancelled, every `PROPOSED` or `CONFIRMED` slot is cancelled with `cancel_reason` `EVENT_CANCELLED`. When the event completes, every `CONFIRMED` slot moves to `DONE`; slots still `PROPOSED` are unaffected by completion. Slot listings exist per event and per area.

### 3.7. Ticketing, Payment, and Parking

A `Spectator` places a ticket order with a `buyer_name` and a non-empty `lines` array, each line pairing a `line_type` — `ADULT_DAY`, `CHILD_DAY`, `ADULT_WEEKEND`, or `CHILD_WEEKEND` — with a `quantity` of at least one; an empty `lines` array, an unknown line type, or a quantity below one is rejected with `ERR_VALIDATION`. Ordering requires posture `PUBLISHED` or `EVENT_OPEN`. The server anchors the order to its buyer by storing the caller's `X-User-ID` as `buyer_user_id`, and the order begins `RESERVED`.

At creation the server computes `quoted_total_cents`, a provisional quote that is never charged: for each line in array order, the unit price is the event price field matching the line's `line_type` (`adult_day_price_cents`, `child_day_price_cents`, `adult_weekend_price_cents`, or `child_weekend_price_cents`), extended by the line's `quantity`; when the order's `created_at` falls on or before the event's `early_bird_cutoff_at` — an inclusive boundary — the extended amount is reduced by the `early_bird_pct` fraction; each line's result is rounded half-up to whole cents before any summation; and the order total is the sum of those rounded lines plus the event's `service_fee_cents`, added after the sum and never itself discounted.

Payment belongs to the buyer alone: the caller's `X-User-ID` must equal the order's `buyer_user_id` (`ERR_FORBIDDEN`), the order must be `RESERVED` (`ERR_INVALID_ORDER_STATUS`), and the payload carries `payment_method` and `payment_reference`, both required strings that are validated but not stored on the order. At payment the charge is recomputed by the same per-line discipline, but with `paid_at` — the logical now — as the pricing timestamp, and early-bird eligibility is re-evaluated against it rather than carried over: an order created before the cutoff but paid after it is charged the undiscounted price. The result is stored as `final_total_cents`, `paid_at` is stamped, and the order moves `RESERVED → PAID`. Order listings for an event filter by `status` with `limit` and `offset`, and a spectator reading an order sees only their own.

At the gate, an organizer checks a paid order in — `PAID → CHECKED_IN` — provided the event is in `EVENT_OPEN` or `RESTRICTED` posture (`ERR_INVALID_EVENT_POSTURE`) and the order is `PAID` (`ERR_INVALID_ORDER_STATUS`).

Refunds move an order `PAID → REFUNDED` at the request of the owning spectator (ownership enforced as `ERR_FORBIDDEN`) or an organizer, with a `reason` of `PATRON_CHOICE` or `EVENT_CONTINGENCY`, and two variants of arithmetic. Because the permitted postures depend on the reason chosen, the `reason` field itself is validated before the posture gate: a missing or unknown `reason` on a `PAID` order yields `ERR_VALIDATION` regardless of posture. Under `PATRON_CHOICE` — permitted in any posture other than `COMPLETED` or `CANCELLED` (`ERR_INVALID_EVENT_POSTURE`) — the retained fee `retained_fee_cents` is `final_total_cents` multiplied by the event's `refund_retain_pct`, rounded half-up, and `refund_amount_cents` is the remainder. Under `EVENT_CONTINGENCY` — permitted only when the event is `CANCELLED` (`ERR_INVALID_EVENT_POSTURE`) — nothing is retained, and the refund pro-rates unused days: total days is the difference between the calendar dates of `event_ends_at` and `event_starts_at` plus one; elapsed days is the difference between the calendar dates of `cancelled_at` and `event_starts_at`, clamped so it never falls below zero and never exceeds total days; the refund is `final_total_cents` multiplied by the ratio of remaining days (total minus elapsed) to total days, rounded half-up. Either way the invariant `refund_amount_cents` plus `retained_fee_cents` equals `final_total_cents` holds; the refund stamps `refund_reason` and `refunded_at`, and every `ACTIVE` parking pass of the order is voided, each decrementing its lot's `allocated_units` by its `units_used`.

Parking passes are issued against a `PAID` order (`ERR_INVALID_ORDER_STATUS`) by its owning spectator, with `vehicle_plate`, `vehicle_class` (`STANDARD` or `OVERSIZE`), and an optional `site_area_id` naming a preferred lot; each issued pass remembers its parent order through `ticket_order_id`. Each pass occupies computed `units_used`: one unit for `STANDARD`, two for `OVERSIZE`. When a lot is named explicitly, it must resolve (`ERR_AREA_NOT_FOUND`), be of kind `PARKING` (`ERR_AREA_KIND_MISMATCH`), be `ACTIVE` (`ERR_AREA_NOT_ACTIVE`), and have room: the lot's `allocated_units` plus the needed units must not exceed `capacity_units`, inclusive (`ERR_PARKING_CAPACITY_EXCEEDED`). When the lot is omitted, the server selects it deterministically: eligibility is every `PARKING` area of the event that is `ACTIVE` and whose remaining capacity — `capacity_units` minus `allocated_units` — is at least the needed units; ranking is by remaining capacity descending; ties break by earliest `created_at`, never by `id`; and an empty pool is rejected with `ERR_NO_PARKING_AVAILABLE`. The chosen lot is echoed back in the pass's `site_area_id`, and issuing the pass recomputes the lot's `allocated_units`. A pass begins `ACTIVE`; voiding it — by the owning spectator or an organizer, valid only from `ACTIVE` (`ERR_INVALID_PASS_STATUS`) — moves it to `VOIDED` and decrements the lot's `allocated_units` by `units_used`. `VOIDED` passes never count toward lot occupancy. Pass listings exist per order and per lot.

### 3.8. Sutler Row: Vendors, Contracts, and Settlement

Period-goods vendors apply for a place on sutler row. A `Vendor`-role caller applies with `business_name`, `wares_description`, the requested `frontage_feet`, and the `requested_days` of vending — both integers of at least one; application requires posture `REGISTRATION_OPEN` or `PUBLISHED`, and anchors ownership per §2.1 — the caller's `X-User-ID` is recorded as `owner_user_id`, or, absent that header, the created vendor's own `id` becomes the self-anchor. The application begins `APPLIED` with `fee_paid_cents` at zero.

Approval is an organizer action valid only from `APPLIED` (`ERR_INVALID_VENDOR_STATUS`). Approval computes `provisional_fee_cents`: the base fee is `frontage_feet` multiplied by `requested_days` multiplied by the event's `vendor_frontage_rate_cents`; when `requested_days` is at least three, the base is reduced by the `vendor_multi_day_discount_pct` fraction and rounded half-up to whole cents; and the fee is the greater of that base and the event's `vendor_min_fee_cents`. The provisional fee never includes the late-insurance surcharge, since no certificate is yet due.

Contracting belongs to the vendor themself — the caller's `X-User-ID` must equal `owner_user_id` (`ERR_FORBIDDEN`) — from `APPROVED`, while the event is in `REGISTRATION_OPEN` or `PUBLISHED` (`ERR_INVALID_EVENT_POSTURE`). The contract payload carries `insurance_cert_ref` and a `fee_payment_cents` amount (a non-negative integer); contracting records the certificate reference, stamps `insurance_uploaded_at` with the logical now, adds `fee_payment_cents` into `fee_paid_cents`, and moves the vendor `APPROVED → CONTRACTED`.

Settlement closes the books after the show, and is an organizer action valid only from `CONTRACTED`. Three gates apply: the event must be `COMPLETED` (`ERR_INVALID_EVENT_POSTURE`); a `SIGNED` `LANDOWNER_USE` agreement must be in force at settlement time — logical now within its inclusive window — else `ERR_AGREEMENT_NOT_IN_FORCE`; and `fee_paid_cents` must be at least `provisional_fee_cents`, else `ERR_VENDOR_BALANCE_OUTSTANDING`. Settlement computes `final_fee_cents` with the same base, multi-day discount, and floor as the provisional fee, and then — because the certificate's arrival is now known — adds the event's flat `vendor_late_insurance_surcharge_cents` when `insurance_uploaded_at` falls strictly after the event's `vendor_insurance_deadline_at`; identical inputs therefore produce a higher final fee when the insurance was late, while a certificate arriving exactly at the deadline escapes the surcharge. The `balance_due_cents` is fixed at settlement as `final_fee_cents` minus `fee_paid_cents`, and the vendor moves to `SETTLED`.

Revocation — by an organizer or safety officer, from `APPLIED`, `APPROVED`, or `CONTRACTED` (`ERR_INVALID_VENDOR_STATUS` from any other state), with an optional `reason` (accepted but not persisted) — moves the vendor to `REVOKED` and releases every `ACTIVE` allocation naming that vendor, each moving to `RELEASED` with its area's `allocated_units` recomputed. Vendor listings exist per event.

### 3.9. Contingencies, Restriction, Completion, and Cancellation

A `SafetyOfficer` raises a contingency alert with an `alert_kind` of `WEATHER`, `FIRE`, or `SECURITY`, a `severity` of `ADVISORY`, `WATCH`, or `RED_FLAG`, and a free-text `message`; alerts may be raised while the event is `PUBLISHED`, `EVENT_OPEN`, or `RESTRICTED`. A new alert begins `OPEN`, and its creation recomputes the event's `restriction_level` per §2.6. When the recomputed level is `RED` while the event stands in `EVENT_OPEN`, the system itself moves the event `EVENT_OPEN → RESTRICTED`, and every program slot of the event with `open_flame` true in `PROPOSED` or `CONFIRMED` is cancelled with `cancel_reason` `CONTINGENCY`. The same transition and the same open-flame cascade are available manually: the organizer or a safety officer may restrict the event from `EVENT_OPEN`, with an optional `reason` (accepted but not persisted).

Restriction is lifted — `RESTRICTED → EVENT_OPEN` — by the organizer or a safety officer only when no `OPEN` `RED_FLAG` alert remains on the event; otherwise the attempt fails with `ERR_RED_ALERTS_OPEN`. The same guard protects opening the gates for the first time: moving `PUBLISHED → EVENT_OPEN` requires that no `OPEN` `RED_FLAG` alert exist, else `ERR_RED_ALERTS_OPEN`. Resolving an alert is a safety-officer action valid only from `OPEN` (`ERR_INVALID_ALERT_STATUS`); it stamps `resolved_at`, moves the alert to `RESOLVED`, and recomputes the `restriction_level` from the remaining open alerts — but it never lifts the event's posture on its own: only the explicit lift-restriction action does that.

Completion — `EVENT_OPEN → COMPLETED` or `RESTRICTED → COMPLETED`, an organizer action — marks the show finished and moves every `CONFIRMED` program slot to `DONE`. Cancellation is the heaviest action in the system: an organizer may cancel from any non-terminal posture, with an optional `reason` (accepted but not persisted), moving the event to `CANCELLED`, stamping `cancelled_at` with the logical now, and running the full cascade hop by hop. First the event's own transition lands; then every ticket order in `PAID` is refunded under the `EVENT_CONTINGENCY` variant — nothing retained, pro-rated by unused days measured to `cancelled_at` — while every order in `RESERVED` is simply cancelled; orders already `CHECKED_IN` (or already `REFUNDED`) are left untouched; then every `ACTIVE` parking pass of a refunded order is voided, decrementing its lot's `allocated_units` by its `units_used`. In the same sweep, every `PROPOSED` or `CONFIRMED` program slot is cancelled with `cancel_reason` `EVENT_CANCELLED`, every `ACTIVE` allocation is released with its area's `allocated_units` recomputed, every vendor in `APPROVED` or `CONTRACTED` is revoked, and every `OPEN` contingency alert is resolved with `resolved_at` set to `cancelled_at`. Both `COMPLETED` and `CANCELLED` are terminal.

## 4. Endpoint Definitions

All endpoints live under the API root. Operations that create a new resource return HTTP 201 with the created resource; operations that modify, transition, or read a resource return HTTP 200. All responses use the envelope of §2.2, and all errors the catalog of §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/events` | Create an event in `PLANNING` posture | EventOrganizer |
| GET | `/events/{event_id}` | Read an event including posture, restriction level, and combatant count | EventOrganizer, AuthenticityOfficer, SafetyOfficer, UnitCommander, Participant, Vendor, Spectator |
| PATCH | `/events/{event_id}` | Update mutable event settings; OCC-guarded; requires `PLANNING` or `REGISTRATION_OPEN` | EventOrganizer |
| POST | `/events/{event_id}/open-registration` | `PLANNING → REGISTRATION_OPEN` | EventOrganizer |
| POST | `/events/{event_id}/publish` | `REGISTRATION_OPEN → PUBLISHED`; requires in-force signed landowner agreement and sufficient signed liability insurance | EventOrganizer |
| POST | `/events/{event_id}/open-gates` | `PUBLISHED → EVENT_OPEN`; blocked while any `RED_FLAG` alert is `OPEN` | EventOrganizer |
| POST | `/events/{event_id}/restrict` | `EVENT_OPEN → RESTRICTED`; cancels open-flame slots | EventOrganizer, SafetyOfficer |
| POST | `/events/{event_id}/lift-restriction` | `RESTRICTED → EVENT_OPEN`; blocked while any `RED_FLAG` alert is `OPEN` | EventOrganizer, SafetyOfficer |
| POST | `/events/{event_id}/complete` | `EVENT_OPEN` or `RESTRICTED → COMPLETED`; `CONFIRMED` slots become `DONE` | EventOrganizer |
| POST | `/events/{event_id}/cancel` | Any non-terminal posture → `CANCELLED`; runs the full cancellation cascade | EventOrganizer |
| POST | `/events/{id}/agreements` | Submit a new agreement version; OCC-guarded; supersedes same-type agreements | EventOrganizer |
| POST | `/agreements/{agreement_id}/sign` | `SUBMITTED → SIGNED`; records signer and time | EventOrganizer |
| GET | `/events/{id}/agreements` | List an event's agreements, all statuses, creation order | EventOrganizer, SafetyOfficer |
| POST | `/units` | Register a unit (bootstrap: caller's `X-User-ID` becomes the unit's id) | UnitCommander |
| GET | `/units/{unit_id}` | Read a unit | UnitCommander, EventOrganizer, AuthenticityOfficer, SafetyOfficer |
| POST | `/units/{unit_id}/vet` | Vet a unit: `SUBMITTED → APPROVED/REJECTED`, or reinstate `SUSPENDED → APPROVED` | EventOrganizer |
| POST | `/units/{unit_id}/suspend` | `APPROVED → SUSPENDED`; depth-three suspension cascade | EventOrganizer |
| GET | `/events/{id}/units` | List an event's units | EventOrganizer, AuthenticityOfficer, SafetyOfficer |
| POST | `/participants` | Register a participant in `DRAFT` | UnitCommander, Participant, EventOrganizer |
| GET | `/participants` | Filtered, paginated list of participants | EventOrganizer, AuthenticityOfficer, SafetyOfficer, UnitCommander, Participant |
| GET | `/participants/{participant_id}` | Read a participant | EventOrganizer, AuthenticityOfficer, SafetyOfficer, UnitCommander, Participant |
| POST | `/participants/{participant_id}/submit` | `DRAFT` or `CHANGES_REQUESTED → SUBMITTED` | UnitCommander, Participant |
| POST | `/participants/{participant_id}/vet` | Authenticity vetting: `SUBMITTED → VETTED / CHANGES_REQUESTED / REJECTED` | AuthenticityOfficer |
| POST | `/participants/{participant_id}/check-in` | `VETTED → CHECKED_IN`; posture, unit, equipment, and supervision gates | EventOrganizer, SafetyOfficer |
| POST | `/participants/{participant_id}/withdraw` | Any non-terminal status → `WITHDRAWN`; equipment and inspection cascade | Participant, UnitCommander, EventOrganizer |
| POST | `/equipment-items` | Declare an equipment item (`DECLARED`) | Participant, UnitCommander, EventOrganizer |
| GET | `/equipment-items/{item_id}` | Read an equipment item | SafetyOfficer, EventOrganizer, UnitCommander, Participant |
| GET | `/participants/{id}/equipment-items` | List a participant's equipment items | SafetyOfficer, EventOrganizer, UnitCommander, Participant |
| POST | `/equipment-items/{item_id}/withdraw` | `DECLARED / INSPECTION_DUE / FAILED → WITHDRAWN`; cancels scheduled inspections | Participant, UnitCommander, EventOrganizer |
| POST | `/equipment-items/{id}/inspections` | Schedule a 45-minute inspection; item becomes `INSPECTION_DUE`; buffered-window conflict check | SafetyOfficer |
| GET | `/equipment-items/{id}/inspections` | List an item's inspections | SafetyOfficer, EventOrganizer |
| POST | `/inspections/{inspection_id}/record` | `SCHEDULED → RECORDED_PASS / RECORDED_FAIL`; drives item to `PASSED` or `FAILED` (`BANNED` at two failures) | SafetyOfficer |
| POST | `/inspections/{inspection_id}/waive` | `RECORDED_FAIL → WAIVED`; segregation of duties enforced; item `FAILED → WAIVED` | SafetyOfficer |
| POST | `/events/{id}/site-areas` | Define a site area; requires `PLANNING`, `REGISTRATION_OPEN`, or `PUBLISHED` | EventOrganizer |
| GET | `/site-areas/{area_id}` | Read a site area including `allocated_units` | EventOrganizer, SafetyOfficer |
| GET | `/events/{id}/site-areas` | List an event's site areas | EventOrganizer, SafetyOfficer |
| POST | `/site-areas/{area_id}/close` | `ACTIVE → CLOSED` | EventOrganizer, SafetyOfficer |
| POST | `/site-areas/{area_id}/allocations` | Allocate camp ground (unit) or sutler booth (vendor) with a half-open window | EventOrganizer |
| GET | `/allocations` | Filtered, paginated list of allocations | EventOrganizer, SafetyOfficer |
| GET | `/allocations/{allocation_id}` | Read an allocation | EventOrganizer, SafetyOfficer |
| POST | `/allocations/{allocation_id}/release` | `ACTIVE → RELEASED`; recomputes the area's `allocated_units` | EventOrganizer |
| POST | `/events/{id}/program-slots` | Propose a program slot on a `DEMO` area | EventOrganizer |
| GET | `/events/{id}/program-slots` | List an event's program slots | EventOrganizer, SafetyOfficer |
| GET | `/site-areas/{id}/program-slots` | List a site area's program slots | EventOrganizer, SafetyOfficer |
| POST | `/program-slots/{slot_id}/confirm` | `PROPOSED → CONFIRMED`; area, flame, combatant, and posture gates | EventOrganizer |
| POST | `/program-slots/{slot_id}/cancel` | `PROPOSED` or `CONFIRMED → CANCELLED` | EventOrganizer, SafetyOfficer |
| POST | `/events/{id}/ticket-orders` | Create a ticket order (`RESERVED`) with provisional quote | Spectator |
| GET | `/events/{id}/ticket-orders` | List an event's ticket orders | EventOrganizer |
| GET | `/ticket-orders/{order_id}` | Read a ticket order (spectators limited to their own) | Spectator, EventOrganizer |
| POST | `/ticket-orders/{order_id}/pay` | `RESERVED → PAID`; computes the final charge at payment time | Spectator |
| POST | `/ticket-orders/{order_id}/refund` | `PAID → REFUNDED`; `PATRON_CHOICE` or `EVENT_CONTINGENCY` arithmetic; voids active passes | Spectator, EventOrganizer |
| POST | `/ticket-orders/{order_id}/check-in` | `PAID → CHECKED_IN` (gate scan) | EventOrganizer |
| POST | `/ticket-orders/{id}/parking-passes` | Issue a parking pass against a paid order; explicit lot or server-selected | Spectator |
| GET | `/ticket-orders/{id}/parking-passes` | List an order's parking passes | Spectator, EventOrganizer |
| GET | `/site-areas/{id}/parking-passes` | List a parking lot's passes | EventOrganizer, SafetyOfficer |
| POST | `/parking-passes/{pass_id}/void` | `ACTIVE → VOIDED`; decrements the lot's `allocated_units` | Spectator, EventOrganizer |
| POST | `/events/{id}/vendors` | Sutler application (`APPLIED`) | Vendor |
| GET | `/events/{id}/vendors` | List an event's vendors | EventOrganizer, SafetyOfficer |
| GET | `/vendors/{vendor_id}` | Read a vendor | Vendor, EventOrganizer |
| POST | `/vendors/{vendor_id}/approve` | `APPLIED → APPROVED`; computes the provisional booth fee | EventOrganizer |
| POST | `/vendors/{vendor_id}/contract` | `APPROVED → CONTRACTED`; records insurance certificate and a fee payment | Vendor |
| POST | `/vendors/{vendor_id}/revoke` | `APPLIED / APPROVED / CONTRACTED → REVOKED`; releases the vendor's allocations | EventOrganizer, SafetyOfficer |
| POST | `/vendors/{vendor_id}/settle` | `CONTRACTED → SETTLED`; final fee with late-insurance surcharge and balance due | EventOrganizer |
| POST | `/events/{id}/contingency-alerts` | Raise an alert (`OPEN`); recomputes restriction level; may force restriction | SafetyOfficer |
| GET | `/events/{id}/contingency-alerts` | List an event's contingency alerts | EventOrganizer, SafetyOfficer |
| POST | `/contingency-alerts/{alert_id}/resolve` | `OPEN → RESOLVED`; recomputes restriction level (posture not auto-lifted) | SafetyOfficer |
| POST | `/_clock/set_current_utc` | Set the logical clock (ISO 8601 UTC); default startup time 2026-05-01T00:00:00Z | EventOrganizer |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in §2 and §3; this catalogue fixes only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_EVENT_NOT_FOUND | 404 |
| ERR_UNIT_NOT_FOUND | 404 |
| ERR_PARTICIPANT_NOT_FOUND | 404 |
| ERR_EQUIPMENT_NOT_FOUND | 404 |
| ERR_INSPECTION_NOT_FOUND | 404 |
| ERR_AREA_NOT_FOUND | 404 |
| ERR_SLOT_NOT_FOUND | 404 |
| ERR_ORDER_NOT_FOUND | 404 |
| ERR_PASS_NOT_FOUND | 404 |
| ERR_VENDOR_NOT_FOUND | 404 |
| ERR_AGREEMENT_NOT_FOUND | 404 |
| ERR_ALERT_NOT_FOUND | 404 |
| ERR_ALLOCATION_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_EVENT_POSTURE | 409 |
| ERR_INVALID_UNIT_STATUS | 409 |
| ERR_INVALID_PARTICIPANT_STATUS | 409 |
| ERR_INVALID_EQUIPMENT_STATUS | 409 |
| ERR_INVALID_INSPECTION_STATUS | 409 |
| ERR_INVALID_SLOT_STATUS | 409 |
| ERR_INVALID_ORDER_STATUS | 409 |
| ERR_INVALID_PASS_STATUS | 409 |
| ERR_INVALID_VENDOR_STATUS | 409 |
| ERR_INVALID_AGREEMENT_STATUS | 409 |
| ERR_INVALID_ALERT_STATUS | 409 |
| ERR_AREA_NOT_ACTIVE | 409 |
| ERR_UNINSPECTED_EQUIPMENT | 409 |
| ERR_SUPERVISOR_REQUIRED | 422 |
| ERR_SUPERVISOR_INELIGIBLE | 422 |
| ERR_SUPERVISION_RATIO_EXCEEDED | 409 |
| ERR_OPEN_FLAME_RESTRICTED | 409 |
| ERR_RED_ALERTS_OPEN | 409 |
| ERR_SOD_SELF_WAIVER | 403 |
| ERR_VALIDATION | 400 |
| ERR_UNIT_NOT_IN_EVENT | 422 |
| ERR_SLOT_OVERLAP | 409 |
| ERR_INSPECTION_WINDOW_CONFLICT | 409 |
| ERR_ALLOCATION_OVERLAP | 409 |
| ERR_ALLOCATION_PARTY_REQUIRED | 422 |
| ERR_AREA_KIND_MISMATCH | 422 |
| ERR_INVALID_TIME_RANGE | 422 |
| ERR_OUTSIDE_EVENT_WINDOW | 422 |
| ERR_AGREEMENT_NOT_IN_FORCE | 409 |
| ERR_INSURANCE_COVERAGE_INSUFFICIENT | 422 |
| ERR_VENDOR_BALANCE_OUTSTANDING | 409 |
| ERR_PARKING_CAPACITY_EXCEEDED | 409 |
| ERR_NO_PARKING_AVAILABLE | 409 |
| ERR_AREA_CAPACITY_EXCEEDED | 409 |
| ERR_NOT_FOUND | 404 |
| ERR_METHOD_NOT_ALLOWED | 405 |

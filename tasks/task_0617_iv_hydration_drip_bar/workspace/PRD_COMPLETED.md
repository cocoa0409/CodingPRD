# IV Hydration & Vitamin Drip Bar API — Product Requirements Document

## 1. Introduction

The IV Hydration & Vitamin Drip Bar platform is the operational backbone for a modern, "Drip Hydration"-style infusion service that delivers vitamin and hydration therapy either at a fixed lounge or at a patient's location via mobile dispatch. The business sells a curated menu of drips (Myers cocktails, NAD therapy, immunity blends) plus à-la-carte add-ons, and every infusion must pass through a regulated clinical pipeline: a good-faith intake and contraindication screening, authorization under a medical director's standing order, signed patient consent, supply and expiry control over the actual fluids and vials drawn, and adverse-reaction reporting. Because the same therapy can be paid for with cash, a membership discount, or pre-purchased package credits, the platform must reconcile finite credit pools and per-line cash pricing with absolute precision.

This document specifies the REST API that drives that pipeline. It is written for the engineers who will implement the service, and it treats the domain first and the wire format second. Two themes recur throughout. The first is **segregation of duties** — the licensed prescriber who signs an order or approves a borderline case must never be the same person who administers the infusion, and the clinician who authors a screening must never be the one who witnesses the consent for that same visit. The second is **temporal correctness** — standing orders, supply lots, lounge hours, route turnaround buffers, and patient age are all evaluated against a single server-controlled logical clock, never against wall-clock time, so that the benchmark behaves deterministically.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares their operational capacity. The system recognizes exactly four roles: `ClinicAdmin`, `IntakeNurse`, `MedicalDirector`, and `Nurse`. If either header is missing or blank, or if `X-User-Role` carries a value that is not one of these four recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are valid but the role is not permitted to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

`ClinicAdmin` is the front-desk and operations operator: this role configures the catalog, registers patients and nurses, creates memberships and lounges, receives and quarantines supply, manages dispatch routes, and drives scheduling, dispatch, and cancellation. `IntakeNurse` performs the good-faith intake and contraindication screening and records patient consent. `MedicalDirector` is the licensed prescriber who signs, activates, and revokes standing orders, approves or declines appointments that require medical review, and reviews and resolves adverse events. `Nurse` is the registered nurse dispatched to perform the infusion (starting and completing it) and may also report adverse events.

Identity semantics differ by role and are load-bearing for the segregation-of-duties rules described later. When `X-User-Role` is `ClinicAdmin`, `IntakeNurse`, or `MedicalDirector`, the `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity's `id`; the server may record it on a resource where a workflow writes it (for example, the `medical_director_user_id` captured on a standing order, the `author_user_id` captured on a screening, the `witness_user_id` captured on a consent, or the `reported_by_user_id` captured on an adverse event), but it never compares the header to any entity's `id`. When `X-User-Role` is `Nurse`, by contrast, `X-User-ID` is the `id` of the acting `Nurse` entity; ownership checks on any resource that references a nurse compare the resource's nurse foreign key to `X-User-ID` — concretely, only the nurse whose `id` equals the appointment's dispatched `nurse_id` may start or complete that infusion.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits; it is read from server wall-clock time and is independent of the logical business clock of §2.4.
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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it must be at least 1 and no greater than 100. The `offset` parameter is the number of items to skip from the front of the result set; when omitted it defaults to 0. A `limit` or `offset` outside these bounds, or any unrecognized filter value, is rejected with `ERR_VALIDATION_PARAM` (HTTP 400).

Unless an endpoint explicitly states otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order, with ties (resources sharing the same `created_at`, common because timestamps are minted from the logical clock) broken by server-side insertion order. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Logical Clock

Every persisted resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp rendered as an ISO 8601 UTC instant with three fractional digits. Both `created_at` and `updated_at` are minted from the logical clock described below (not from wall-clock time), so they read whatever instant the logical clock holds at creation or mutation. All entities in this system are mutable and therefore also carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits, refreshed on every mutation) and an integer `version` that begins at 1 on creation and increments by one on each mutation. Where a workflow below states that an operation "increments the version" of an entity, it also refreshes that entity's `updated_at`.

The platform runs on a single logical clock rather than wall-clock time. On server startup the clock reads exactly `2026-01-01T00:00:00Z`, and it holds that value until an administrator advances it. Every deadline, expiry, in-force window, and age computation in this specification — standing-order effectivity, supply-lot expiry, lounge open and close windows, the rule that an infusion may only start once its scheduled instant has arrived, and the derivation of patient age — reads this clock. The clock is moved only through an administrator-only test-driving capability that sets the clock to a supplied `to_iso8601` instant.

### 2.5. Optimistic Concurrency Control

Two write operations require the client to prove it is acting on a current view of a parent entity, and both reject stale writes rather than silently overwriting.

Scheduling an appointment requires an `expected_appointment_version` field whose value must equal that appointment's current `version`. If a prior write — for example a re-submitted intake that superseded the screening, or a cancellation — has advanced the appointment's `version` since the client last read it, the scheduling request is rejected with `ERR_STALE_VERSION` (HTTP 412); this prevents the scheduler's supply reservation and credit decrement from being applied against an out-of-date appointment state.

Medical-director approval likewise requires `expected_appointment_version` to match the appointment's current `version`, and it additionally accepts `expected_membership_version`. When the appointment carries a membership against which credits will be redeemed, `expected_membership_version` must equal that membership's current `version`; if a prior approval has already drawn down credits, or a suspend/reinstate has advanced the membership's `version` since the client last observed it, the approval is rejected with `ERR_STALE_VERSION` (HTTP 412), which prevents the finite credit pool from being double-spent against a stale view. The membership check is applied only when `expected_membership_version` is actually supplied: an omitted `expected_membership_version` skips the membership stale-version check entirely (even when a membership is attached), and a supplied `expected_membership_version` is ignored when the appointment has no attached membership. No endpoint other than scheduling and medical-director approval takes a version field, and those that do treat the version fields as required inputs of the operation rather than optional hints.

### 2.6. Validation Order and Precedence

When several conditions could each reject a request, they are evaluated in a fixed precedence so that the returned `error_id` is deterministic. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then role authorization for the endpoint (`ERR_FORBIDDEN_ROLE`), then existence of every path-referenced and foreign-key-referenced resource validated left to right (`ERR_NOT_FOUND`), then well-formedness of the request body (`ERR_INVALID_REQUEST`), then whether the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`). Only after all of those pass does the system evaluate the optimistic-concurrency check on the parent version (`ERR_STALE_VERSION`), and only after that does it evaluate the domain-specific business rules.

Among the business rules that share the scheduling and approval endpoints, the order is: the screening-not-blocked safety check (`ERR_SCREENING_BLOCKED`) is evaluated before the signed-consent check (`ERR_CONSENT_MISSING`), which is evaluated before the segregation-of-duties check (`ERR_SEGREGATION_OF_DUTIES`), which is evaluated before the standing-order check (`ERR_NO_STANDING_ORDER`), which is evaluated before the slot/capacity check (`ERR_SLOT_CONFLICT`), which is evaluated before the supply-availability check (`ERR_SUPPLY_UNAVAILABLE`), which is evaluated before the membership-credit check (`ERR_CREDIT_INSUFFICIENT`). A request that violates more than one rule surfaces the earliest one in this order.

### 2.7. Nested Resource Retrieval and Reverse Lookups

Several read paths address a child collection through a parent identifier — for example the screenings, consents, or adverse events belonging to an appointment, the memberships referenced by a patient, the nurses rostered to a lounge, or the routes belonging to a nurse. For any such path the system validates the identifiers left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) on the first identifier in the path that does not correspond to an existing resource, before attempting to resolve anything further to its right.

### 2.8. Monetary Precision and Rounding

All prices and charges are expressed in whole integer cents. Wherever the visit-charge logic applies a membership discount fraction to a list price, the discounted line amount is rounded half up to the nearest whole cent, and the rounding is applied to each individual line before the lines are summed — never to a running subtotal after summation. There is no sub-cent representation anywhere in the API; computed monetary fields are integers.

### 2.9. Supply, Expiry, and FEFO Discipline

The fluids, vitamins, and push medications drawn for every infusion are tracked as supply lots, each describing what it supplies via `item_kind` (either `DRIP_BASE` or `ADDON`), the specific drip tier or add-on code it covers via `tier_or_code`, its manufacturer `lot_number`, the `units_total` received, and an `expires_at` instant. The lot also exposes the computed counters `units_reserved` and `units_consumed`, and a computed `status` that is one of `AVAILABLE`, `EXHAUSTED`, `EXPIRED`, or `QUARANTINED`. The number of free units in a lot is its `units_total` minus `units_reserved` minus `units_consumed`. A lot is unusable for any slot whose `start_at` is at or after the lot's `expires_at`; the in-force window is half-open, so a lot remains usable exactly while the slot's `start_at` is strictly before `expires_at`.

Selection of which lot to draw follows First-Expiry-First-Out (FEFO): among the candidate lots for a line, the system always chooses the one expiring soonest. The cascade and counter semantics of reservation, consumption, expiry, exhaustion, and quarantine are detailed in §3.

### 2.10. State Enumerations

For precise reference, the lifecycle states used throughout §3 are enumerated here. An `Appointment.status` is one of `REQUESTED`, `SCREEN_PENDING`, `REQUIRES_MD_REVIEW`, `SCHEDULED`, `DISPATCHED`, `IN_PROGRESS`, `COMPLETED`, `DECLINED`, or `CANCELLED`. A `StandingOrder.status` is one of `DRAFT`, `ACTIVE`, `EXPIRED`, or `REVOKED`. A `Membership.status` is one of `ACTIVE` or `SUSPENDED`. A `DispatchRoute.status` is one of `PLANNING`, `LOCKED`, or `CLOSED`. An `AdverseEvent.status` is one of `REPORTED`, `UNDER_REVIEW`, or `RESOLVED`. An `IntakeScreening.status` is one of `SUBMITTED` or `SUPERSEDED`, and its `outcome` is one of `CLEARED`, `REQUIRES_MD_REVIEW`, or `BLOCKED`. A `Consent.status` is one of `SIGNED` or `REVOKED`. A `SupplyLot.status` is one of `AVAILABLE`, `EXHAUSTED`, `EXPIRED`, or `QUARANTINED`.

## 3. Business Logic & Workflows

### 3.1. Catalog, People, and Places

Before any infusion can be booked, a `ClinicAdmin` configures the catalog and the operational assets. A drip menu item is created with a display `name` (such as "Myers Cocktail"), a `tier` that is one of `MYERS`, `NAD`, or `IMMUNITY`, and a `base_price_cents` cash list price that must be zero or greater. Two clinical flags shape downstream behavior: `requires_standing_order`, which defaults to true and means an appointment for this drip needs an in-force standing order covering its tier; and `g6pd_sensitive`, which defaults to false and, when true, causes the patient's G6PD-deficiency intake flag to raise the contraindication score for this drip. A menu item also carries an `active` flag (default true); an inactive item cannot accept new appointments. Add-ons are created similarly, each with a `name` (such as "Glutathione Push"), a `code` that is one of `GLUTATHIONE`, `B12`, `ZOFRAN`, `TORADOL`, or `VITC_HIGH`, a `price_cents` list price of zero or greater, and an `active` flag (default true).

A patient is registered with a `full_name`, a `date_of_birth` (an ISO 8601 date used to derive whether the patient is over 70 at the time of an infusion; it is parsed into and serialized back as a full ISO 8601 UTC instant with three fractional digits, so a date-only input such as `1990-01-01` is returned as `1990-01-01T00:00:00.000Z`), and an optional `membership_id` that links the patient to a membership (null when the patient has no membership). Each patient also exposes the computed `open_adverse_event_count`, which begins at 0 and reflects the number of that patient's adverse events whose status is either `REPORTED` or `UNDER_REVIEW`; it is recomputed whenever an adverse event for that patient is created or resolved. Patients may be listed and filtered by `membership_id` as a reverse lookup from a membership to the patients that reference it.

Nurses are registered with a `full_name`, an RN `license_number`, an optional `home_lounge_id` identifying the lounge the nurse is rostered to (null for mobile-only RNs), and a `status` of either `AVAILABLE` or `OFF_DUTY` (default `AVAILABLE`). Lounges are created with a `name`, a `bay_count` of at least 1 describing how many infusion bays can run concurrently, and two operating-window fields measured in minutes after midnight UTC: `open_minute_of_day` (default 480, i.e. 08:00) in the range 0 through 1439, and `close_minute_of_day` (default 1200, i.e. 20:00) in the range 0 through 1440. A lounge can be read directly, and the nurses rostered to it can be retrieved as a reverse lookup over `home_lounge_id`.

### 3.2. Memberships, Packages, and Credit Pools

A membership represents a patient's package and discount entitlement and is created by a `ClinicAdmin`. Each membership carries a `tier` that is one of `NONE`, `GOLD`, or `PLATINUM`; a `covered_drip_tier` that is one of `MYERS`, `NAD`, or `IMMUNITY` and names the single drip tier that a drip credit may be redeemed against; a `drip_credits_total` of zero or greater representing whole-visit drip credits granted at purchase (optional, defaulting to 0 when omitted); and an `addon_credits_total` of zero or greater representing the per-add-on credits granted (optional, defaulting to 0 when omitted). The `tier` and `covered_drip_tier` are required. At creation, the computed `drip_credits_remaining` is initialized to equal `drip_credits_total` and the computed `addon_credits_remaining` is initialized to equal `addon_credits_total`. A membership's computed `status` is one of `ACTIVE` or `SUSPENDED` and starts `ACTIVE`.

The remaining-credit fields move with the appointment lifecycle. `drip_credits_remaining` is `drip_credits_total` minus the drip credits consumed by visits that proceed; it is decremented when a visit redeems a drip credit and restored when such a visit is cancelled. `addon_credits_remaining` behaves the same way for add-on credits. A membership can be read (its read response includes the remaining-credit fields and the current `version`).

A `ClinicAdmin` may move a membership from `ACTIVE` to `SUSPENDED`; this sets `status` to `SUSPENDED` and increments the membership's `version` by one. The reverse transition takes a `SUSPENDED` membership back to `ACTIVE`, setting `status` to `ACTIVE` and incrementing `version` by one. Neither transition has any precondition beyond the membership being in the appropriate state. Because suspending a membership advances its `version`, it can also cause a later medical-director approval that pinned the earlier version to be rejected on the stale-version check described in §2.5. The memberships referenced by a given patient (zero or one) can be retrieved as a reverse lookup.

### 3.3. Standing Orders and Medical Authorization

A standing order is the medical director's blanket authorization for a drip tier over a window of time. A `MedicalDirector` creates one in `DRAFT` status by supplying the `medical_director_user_id` (the opaque identifier of the signing director), a `covered_tier` of `MYERS`, `NAD`, or `IMMUNITY`, an `effective_from` instant before which the order is not in force, and an `expires_at` instant at which it lapses. The in-force window is half-open: the order authorizes a drip whose slot begins at or after `effective_from` and strictly before `expires_at`.

Activation moves a standing order from `DRAFT` to `ACTIVE`. It is permitted only when the caller's `X-User-ID` equals the order's `medical_director_user_id`, when the logical clock is still before `expires_at`, and when `effective_from` is before `expires_at`; on success it sets `status` to `ACTIVE` and increments the order's `version` by one. Each of these three activation preconditions failing (a caller who is not the signing director, a logical clock at or after `expires_at`, or an `effective_from` not strictly before `expires_at`) is rejected with `ERR_INVALID_STATE` (HTTP 409). An `ACTIVE` order can be revoked by the same director — again the caller's `X-User-ID` must equal `medical_director_user_id`, otherwise the revoke is rejected with `ERR_INVALID_STATE` — which moves it to the terminal `REVOKED` state and increments `version` by one. Separately, an `ACTIVE` order whose `expires_at` has been reached or passed (the logical clock is at or after `expires_at`) is treated as `EXPIRED`; this lapse is evaluated when the order is used or read, and a lapsed order moves to the terminal `EXPIRED` state. Attempting a transition that is not defined from the order's current state — for instance activating an order that is not `DRAFT` — is rejected with `ERR_INVALID_STATE`. Standing orders can be read individually and listed with optional filters on `covered_tier` and `status`.

### 3.4. Requesting an Appointment

A `ClinicAdmin` or `IntakeNurse` requests an appointment, which is the central entity of the system. The request body names the `patient_id`, the `menu_item_id` for the drip being booked, an optional ordered `addon_ids` array of add-on identifiers (defaulting to an empty list, where redemption and rounding later follow this exact order), the `location_type` of either `LOUNGE` or `MOBILE`, an optional `lounge_id`, the `start_at` instant in ISO 8601 UTC, an optional `duration_minutes` slot length (default 60, at least 15, with the slot ending at `start_at` plus `duration_minutes`), and an optional `membership_id` naming the membership that will apply discount and credits to this visit (null for a cash visit). The body must be well-formed — required fields present, enum values valid, integers in range — and crucially `lounge_id` must be present when `location_type` is `LOUNGE` and must be absent when `location_type` is `MOBILE`; a violation of any of these, or an empty element in `addon_ids`, is rejected with `ERR_INVALID_REQUEST` (HTTP 422).

A newly requested appointment begins in `REQUESTED` status. Several fields are computed by the workflow rather than supplied at request time and start at their defaults: `route_id` (null until a mobile appointment is assigned to a route stop), `nurse_id` (null until dispatch), `standing_order_id` (null until pinned at schedule time), `amount_charged_cents` (null until pinned at schedule or approval), `drip_credit_used` (0), and `addon_credits_used` (0). Appointments can be read individually and listed with filters on `patient_id`, `menu_item_id`, `membership_id`, `lounge_id`, `route_id`, `nurse_id`, `standing_order_id`, and `status`.

### 3.5. Intake Screening and the Contraindication Score

An `IntakeNurse` performs the good-faith screening for an appointment, an action that both authors a new screening and submits it in a single step. It is allowed whenever the appointment is in `REQUESTED`, `SCREEN_PENDING`, or `REQUIRES_MD_REVIEW` status. The screening request supplies the `author_user_id` (the opaque identifier of the authoring intake nurse) and five boolean contraindication flags, each defaulting to false: `pregnancy`, `renal_impairment`, `cardiac_history`, `g6pd_deficiency`, and `recent_adverse_event`. Submitting an intake supersedes any prior `SUBMITTED` screening for that appointment by marking it `SUPERSEDED`, creates a new screening row in `SUBMITTED` status, recomputes that screening's `contraindication_score` and `outcome`, sets the appointment's `status` to `SCREEN_PENDING`, and increments the appointment's `version` by one. Re-intake is therefore a cycle: an appointment can be screened again from `REQUESTED`, `SCREEN_PENDING`, or `REQUIRES_MD_REVIEW`, always returning to `SCREEN_PENDING`, and only the latest `SUBMITTED` screening is authoritative for scheduling or approval. Persisted screening rows are only ever `SUBMITTED` or `SUPERSEDED`.

The `contraindication_score` is an integer sum of weights for the active flags. A true `pregnancy` flag contributes 40 points, `renal_impairment` contributes 30, `cardiac_history` contributes 25, and `recent_adverse_event` contributes 20. The `g6pd_deficiency` flag contributes 35 points, but only when the booked menu item is `g6pd_sensitive`; for a drip that is not g6pd-sensitive the G6PD flag contributes nothing, which means the identical set of flags can yield a different score and even a different outcome depending on the drip. Finally, if the patient is at least 70 years old at the appointment's `start_at` — that is, the time elapsed from `date_of_birth` to `start_at` is 70 years or more — an additional 10 points are added. No rounding is applied; the score is an integer point total.

The `outcome` is derived from the score against two pinned thresholds. A score of 60 or more yields `BLOCKED`. A score of at least 40 but less than 60 yields `REQUIRES_MD_REVIEW`. A score below 40 yields `CLEARED`. These boundaries are exact: 60 is blocked, 59 requires review, 40 requires review, and 39 is cleared. A screening can be read individually (exposing its score, outcome, and status), and the screenings for an appointment can be retrieved as a reverse lookup, with the latest `SUBMITTED` row being authoritative.

### 3.6. Consent and Segregation of Duties

Before an appointment can be scheduled or approved, a patient consent must exist for it in `SIGNED` status. A consent is recorded by an `IntakeNurse` or `ClinicAdmin` and names the `appointment_id`, a `signed_by_patient` boolean that must be true (a consent submitted with `signed_by_patient` not equal to true is rejected with `ERR_CONSENT_NOT_AFFIRMED`, HTTP 422), and a `witness_user_id` identifying the staff witness. The witness identity is constrained by segregation of duties: the `witness_user_id` recorded for an appointment must differ from the `author_user_id` of that appointment's screening; if they collide, the consent is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409). A consent begins in `SIGNED` status.

Consent can be revoked by an `IntakeNurse`, `ClinicAdmin`, or `MedicalDirector`, which is allowed only while the consent is `SIGNED` and moves it to the terminal `REVOKED` state. Because a `REVOKED` consent no longer satisfies the "a `SIGNED` consent exists" precondition, revoking before scheduling blocks the visit. Consents can be read individually and retrieved for an appointment as a reverse lookup.

### 3.7. Scheduling: the Clearance Fork

Scheduling is performed by a `ClinicAdmin` and is where the appointment forks based on its screening outcome. The request carries `expected_appointment_version`, which must match the appointment's current `version` per §2.5. Scheduling is only defined from `SCREEN_PENDING`. If the latest `SUBMITTED` screening's `outcome` is `BLOCKED`, the request is rejected with `ERR_SCREENING_BLOCKED` (HTTP 409) — a blocked screening can never be scheduled or approved. If the latest screening's `outcome` is `REQUIRES_MD_REVIEW`, scheduling does not complete the booking; instead it forks the appointment from `SCREEN_PENDING` to `REQUIRES_MD_REVIEW` and increments its `version` by one, deferring the booking to a medical director.

When the latest screening's `outcome` is `CLEARED`, scheduling drives the appointment from `SCREEN_PENDING` to `SCHEDULED`, subject to a battery of preconditions evaluated in the precedence of §2.6. A `SIGNED` consent must exist for the appointment, or the request is rejected with `ERR_CONSENT_MISSING` (HTTP 409). The booked menu item must be `active`. If the menu item's `requires_standing_order` is true, there must exist an `ACTIVE` standing order covering the menu item's tier and in force at `start_at` — meaning its `effective_from` is at or before `start_at` and its `expires_at` is strictly after `start_at` — otherwise the request is rejected with `ERR_NO_STANDING_ORDER` (HTTP 409). When more than one in-force `ACTIVE` order covers the tier, the one with the earliest `created_at` (insertion order breaking ties) is chosen. The chosen order's identifier is pinned onto the appointment's `standing_order_id`. For a `LOUNGE` appointment the slot must satisfy the lounge window and bay-capacity rule of §3.8, or the request is rejected with `ERR_SLOT_CONFLICT` (HTTP 409). Sufficient non-expired supply must be reservable for the drip and every add-on, or the request is rejected with `ERR_SUPPLY_UNAVAILABLE` (HTTP 409). On success the system reserves one unit on the FEFO-chosen lot for the drip line and for each add-on line (described in §3.10), computes `amount_charged_cents` via the visit-charge waterfall (§3.11) and decrements the membership credits accordingly, sets `status` to `SCHEDULED`, and increments `version` by one.

### 3.8. Lounge Capacity and Operating Windows

A lounge slot occupies the half-open interval from `start_at` to `start_at` plus `duration_minutes`. Two lounge appointments at the same lounge conflict exactly when their half-open intervals overlap — that is, when the candidate's `start_at` is strictly before the other's end and the other's `start_at` is strictly before the candidate's end. Appointments that merely touch at a boundary (one ending at precisely the instant the next begins) do not overlap, so back-to-back lounge bookings are allowed and no turnaround buffer is imposed at a lounge. The concurrent count is the number of lounge appointments at that lounge in `SCHEDULED`, `DISPATCHED`, or `IN_PROGRESS` status whose interval overlaps the candidate's; scheduling is rejected when that count is already equal to or greater than the lounge's `bay_count`, since capacity is exactly `bay_count` concurrent bays.

The slot must also fall within the lounge's operating window. Converting the slot to minutes after midnight UTC, the start minute must be at or after `open_minute_of_day` and the end minute must be at or before `close_minute_of_day`, and the slot must not cross midnight. A slot that violates either the capacity rule or the window rule is rejected with `ERR_SLOT_CONFLICT`.

### 3.9. Medical-Director Review, Dispatch, Start, and Completion

When an appointment sits in `REQUIRES_MD_REVIEW`, a `MedicalDirector` resolves it. Approval drives the appointment from `REQUIRES_MD_REVIEW` to `SCHEDULED` and carries `expected_appointment_version` (and, when a membership is in play, `expected_membership_version`) per §2.5. Approval is forbidden when the caller's `X-User-ID` equals the `author_user_id` of the latest screening — the reviewer must not be the screening author — and that collision is rejected with `ERR_SEGREGATION_OF_DUTIES`. Approval enforces the same downstream gates as the cleared scheduling path: the screening must not be `BLOCKED` (`ERR_SCREENING_BLOCKED`), a `SIGNED` consent must exist (`ERR_CONSENT_MISSING`), the standing-order requirement must be met with the order pinned to `standing_order_id` (`ERR_NO_STANDING_ORDER`), supply must be reservable (`ERR_SUPPLY_UNAVAILABLE`), and credits must suffice (`ERR_CREDIT_INSUFFICIENT`). On success it pins the standing order, reserves supply via FEFO, computes `amount_charged_cents`, decrements membership credits, sets `status` to `SCHEDULED`, and increments `version` by one. Alternatively the director may decline — again the caller's `X-User-ID` must differ from the screening `author_user_id` — moving the appointment from `REQUIRES_MD_REVIEW` to the terminal `DECLINED` state and incrementing `version` by one.

Dispatch is performed by a `ClinicAdmin` on a `SCHEDULED` appointment and supplies the `nurse_id` and, for mobile visits, an optional `route_id`. The named nurse's `status` must be `AVAILABLE`, and a nurse whose `status` is not `AVAILABLE` is rejected with `ERR_INVALID_STATE` (HTTP 409). Segregation of duties applies here too: the dispatched nurse's `X-User-ID` must differ from the `medical_director_user_id` of the appointment's standing order, and a collision is rejected with `ERR_SEGREGATION_OF_DUTIES` — the prescriber who authorized the drip may not also administer it. For a mobile appointment there must be a `PLANNING` dispatch route for that nurse on the service date of `start_at`, and the candidate stop must satisfy the route turnaround buffer described in §3.12. A mobile dispatch with no `route_id` supplied, a `route_id` whose route belongs to a different nurse, or a route whose `service_date` does not match the UTC calendar date of `start_at` is rejected with `ERR_SLOT_CONFLICT` (HTTP 409); a route that is not `PLANNING` (i.e. `LOCKED` or `CLOSED`) is rejected with `ERR_ROUTE_LOCKED` (HTTP 409); and a candidate that violates the turnaround buffer is rejected with `ERR_SLOT_CONFLICT`. On success dispatch sets the appointment's `nurse_id`; for a mobile appointment it also sets the `route_id` and increments that route's `stop_count`; it then sets `status` to `DISPATCHED` and increments `version` by one.

The dispatched nurse starts the infusion, which is defined only from `DISPATCHED`. The caller's `X-User-ID` must equal the appointment's `nurse_id`, and the logical clock must be at or after `start_at` — an infusion cannot begin before its scheduled instant; a caller who is not the dispatched nurse and a clock that is still before `start_at` are each rejected with `ERR_INVALID_STATE` (HTTP 409). Starting moves the appointment from `DISPATCHED` to `IN_PROGRESS` and increments `version` by one. The same nurse completes the infusion from `IN_PROGRESS`; again the caller's `X-User-ID` must equal `nurse_id`, and a mismatch is rejected with `ERR_INVALID_STATE`. Completion moves the reserved supply units to consumed (for each line decreasing `units_reserved` by one and increasing `units_consumed` by one, marking the lot `EXHAUSTED` when `units_consumed` plus `units_reserved` equals `units_total`), finalizes the membership credit consumption with no restoration, sets `status` to `COMPLETED`, and increments `version` by one.

### 3.10. Supply Reservation, Consumption, and Lot Lifecycle

A `ClinicAdmin` receives a supply lot by supplying its `item_kind`, `tier_or_code`, `lot_number`, a `units_total` of at least 1, and an `expires_at` instant; on receipt `units_reserved` and `units_consumed` are both 0 and the lot is `AVAILABLE`. Lots can be read and listed with filters on `item_kind`, `tier_or_code`, and `status`.

When a visit is scheduled or approved, the system reserves exactly one unit for the drip line and one unit for each add-on line. For each line it considers only candidate lots whose `item_kind` matches the line (`DRIP_BASE` for the drip, `ADDON` for an add-on), whose `tier_or_code` equals the line's key (the drip tier, or the add-on code), whose `status` is `AVAILABLE`, whose `expires_at` is strictly after the appointment's `start_at`, and which have at least one free unit (`units_total` minus `units_reserved` minus `units_consumed` is one or more). If no candidate exists for any required line, the operation is rejected with `ERR_SUPPLY_UNAVAILABLE`. Among candidates the system applies FEFO: it sorts by `expires_at` ascending and breaks ties by `created_at` ascending, then picks the first. Reserving increments that lot's `units_reserved` by one. Completion later moves each already-reserved unit from reserved to consumed as described in §3.9, and cancellation releases each reserved unit by decrementing `units_reserved` by one. Because the per-line reservation does not persist which lot it drew, both completion and cancellation re-derive the lines (the drip first, then the add-ons in `addon_ids` order) and, for each line key, select among the lots that currently hold a reserved unit for that key by the same FEFO ordering used at reservation (`expires_at` ascending, then `created_at` ascending, then insertion order), decrementing that lot.

A lot's `status` is otherwise driven by the clock and by administrative action. When the logical clock reaches or passes a lot's `expires_at` and the lot has no reserved units (`units_reserved` is 0), the lot becomes `EXPIRED` and is no longer selectable by FEFO; this lapse is evaluated on read, on list, and on reservation attempts. A `ClinicAdmin` may quarantine an `AVAILABLE` lot — for example on a recall — but only when `units_reserved` is 0; quarantine sets `status` to `QUARANTINED` and increments the lot's `version` by one, and attempting to quarantine a lot that still has reserved units is rejected with `ERR_LOT_HAS_RESERVATIONS` (HTTP 409). The exhaustion transition to `EXHAUSTED` occurs on completion when consumed-plus-reserved reaches `units_total`, as already noted.

### 3.11. The Visit-Charge Waterfall

At schedule time (for a cleared appointment) or at approval time (for an MD-reviewed appointment), the system computes `amount_charged_cents` and decides how membership credits and discounts apply. The computation proceeds in three stages over the drip line and the add-on lines, processed in the order given by `addon_ids`.

First, the discount fraction is determined by membership tier, but only when a membership is present and its `status` is `ACTIVE`: a `NONE`-tier membership and the cash case both yield a discount fraction of 0.000, a `GOLD` membership yields 0.150, and a `PLATINUM` membership yields 0.225. If no membership applies or the membership is not `ACTIVE`, the discount fraction is 0.

Second, the credit waterfall runs in a pinned order. The visit redeems one drip credit — setting `drip_credit_used` to 1 — only when an `ACTIVE` membership is present, that membership's `covered_drip_tier` equals the booked menu item's tier, and the membership's `drip_credits_remaining` is greater than 0; otherwise `drip_credit_used` stays 0. Then `addon_credits_used` starts at 0 and the add-ons are processed in their given order: for each add-on, if `addon_credits_remaining` minus the add-on credits already used so far on this visit is greater than 0, that add-on is covered by a credit and `addon_credits_used` is increased by 1; otherwise that add-on remains a cash line. This means the leading add-ons in the list are the ones that consume credits when credits run short.

Third, the cash lines are priced. A cash line is the drip when it was not credit-covered, plus every add-on that remained a cash line. Each cash line's amount is its list price (the menu item's `base_price_cents` for the drip, or the add-on's `price_cents`) multiplied by one minus the discount fraction, rounded half up to a whole cent — rounded per line, as §2.8 requires. The cash subtotal is the sum of these per-line rounded amounts. A mobile surcharge of 9,500 cents is then added when `location_type` is `MOBILE` and is zero otherwise; this surcharge is never discounted and never coverable by a credit. The final `amount_charged_cents` is the cash subtotal plus the surcharge. For a cash visit (no membership, or a membership that is not `ACTIVE`) the discount fraction is 0, no credits are consumed, every line is charged at full list price, and the mobile surcharge still applies for a mobile visit.

A credit redemption may never drive any credit balance below zero, and only an `ACTIVE` membership ever redeems credits; an attempt that would over-draw a credit pool of an `ACTIVE` membership is rejected with `ERR_CREDIT_INSUFFICIENT` (HTTP 409). A non-`ACTIVE` membership attached to a schedulable visit is not a rejected redemption attempt: as Stage 1, Stage 2, and Stage 3 above specify, it redeems no credits and is priced as a cash visit, so scheduling or approval proceeds and `ERR_CREDIT_INSUFFICIENT` is not raised on its account. When a scheduled or dispatched visit is later cancelled, the credits it consumed are restored: `drip_credits_remaining` is increased by `drip_credit_used` and `addon_credits_remaining` is increased by `addon_credits_used`. Completion, by contrast, finalizes consumption permanently and restores nothing.

### 3.12. Mobile Routes and Turnaround Buffers

A `ClinicAdmin` creates a mobile dispatch route for an RN by supplying the `nurse_id`, a `service_date` (an ISO 8601 UTC-midnight date that the route covers, on which all of its stops must start; it is parsed into and serialized back as a full ISO 8601 UTC instant with three fractional digits), and an optional `turnaround_minutes` buffer of zero or greater (default 30) that is enforced between consecutive mobile stops. A new route starts with a `stop_count` of 0 and `status` `PLANNING`. The `stop_count` tracks the number of non-cancelled appointments currently assigned to the route; it is incremented when a mobile appointment is dispatched onto the route and decremented when such an appointment is cancelled. Routes can be read, and the routes for a nurse can be retrieved as a reverse lookup with an optional `service_date` filter.

When a mobile appointment is dispatched onto a route, the candidate stop occupies the half-open interval from `start_at` to `start_at` plus `duration_minutes`, and the route's `turnaround_minutes` is the required buffer. For every other non-cancelled stop already on the route, the candidate is acceptable only if the candidate ends at least the buffer ahead of that stop's start, or that stop ends at least the buffer ahead of the candidate's start — in other words, consecutive stops must be separated by at least the buffer of turnaround on whichever side they abut. The buffer comparison is inclusive: a gap exactly equal to the buffer is allowed, and a gap smaller than the buffer is rejected. A candidate that violates the buffer against any existing stop is rejected with `ERR_SLOT_CONFLICT`. Unlike lounges, mobile routes always require this non-zero turnaround between adjacent stops.

A `ClinicAdmin` locks a route once it has at least one stop (`stop_count` is 1 or more), moving it from `PLANNING` to `LOCKED` and incrementing its `version` by one; a lock attempt on a route that is not `PLANNING`, or on a `PLANNING` route whose `stop_count` is 0, is rejected with `ERR_INVALID_STATE` (HTTP 409). A locked route accepts no further stops, and any dispatch attempt that would add a stop to a `LOCKED` or `CLOSED` route is rejected with `ERR_ROUTE_LOCKED` (HTTP 409). A `LOCKED` route can be closed once every appointment assigned to it is `COMPLETED` or `CANCELLED`, moving it to the terminal `CLOSED` state and incrementing `version` by one; a close attempt on a route that is not `LOCKED`, or while any assigned appointment is neither `COMPLETED` nor `CANCELLED`, is rejected with `ERR_INVALID_STATE`.

### 3.13. Cancellation and its Reversals

A `ClinicAdmin` may cancel an appointment that is not yet terminal — that is, while it is in `REQUESTED`, `SCREEN_PENDING`, `REQUIRES_MD_REVIEW`, `SCHEDULED`, or `DISPATCHED`. Cancellation unwinds every commitment the appointment had accumulated: it releases any reserved supply units by decrementing `units_reserved` by one on each reserved line; it restores the membership credits by increasing `drip_credits_remaining` by the appointment's `drip_credit_used` and `addon_credits_remaining` by its `addon_credits_used`; if the appointment had been routed (its `route_id` is set), it decrements that route's `stop_count`; and it sets the appointment's `status` to `CANCELLED` and increments its `version` by one. A cancellation thus advances the appointment's `version`, which can later cause a stale-version rejection on any operation that had pinned the earlier version.

### 3.14. Adverse-Event Reporting and Review

A `Nurse` or `MedicalDirector` reports an adverse reaction that occurred during or after an infusion by naming the `appointment_id`, the `reported_by_user_id` of the reporter, a `severity` of `MILD`, `MODERATE`, or `SEVERE`, and a free-text `description`. A reaction may only be reported against an appointment that is `IN_PROGRESS` or `COMPLETED`. A new adverse event begins in `REPORTED` status, and its creation recomputes the patient's `open_adverse_event_count` upward, since the new event is open. Adverse events can be read individually and retrieved for an appointment as a reverse lookup.

A `MedicalDirector` moves a `REPORTED` event to `UNDER_REVIEW` (allowed only while the event is `REPORTED`), which increments the event's `version` by one. The director then resolves an `UNDER_REVIEW` event (allowed only while it is `UNDER_REVIEW`), moving it to the terminal `RESOLVED` state, recomputing the patient's `open_adverse_event_count` downward since the event is no longer open, and incrementing the event's `version` by one. Because `open_adverse_event_count` counts only events that are `REPORTED` or `UNDER_REVIEW`, creation raises it and resolution lowers it, while a transition merely from `REPORTED` to `UNDER_REVIEW` leaves the count unchanged.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including every state-transition action and the logical-clock control — return `200 OK`. Readers should reconstruct each endpoint's request body, response body, and side effects from the §3 narratives; the table below is intentionally limited to method, path, description, and authorization.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | ClinicAdmin |
| POST | `/menu-items` | Create a drip menu item | ClinicAdmin |
| GET | `/menu-items/{id}` | Read a menu item | ClinicAdmin, IntakeNurse, MedicalDirector, Nurse |
| GET | `/menu-items` | List menu items | ClinicAdmin, IntakeNurse, MedicalDirector, Nurse |
| POST | `/add-ons` | Create an add-on | ClinicAdmin |
| GET | `/add-ons` | List add-ons | ClinicAdmin, IntakeNurse, MedicalDirector, Nurse |
| POST | `/patients` | Register a patient | ClinicAdmin, IntakeNurse |
| GET | `/patients/{id}` | Read a patient | ClinicAdmin, IntakeNurse, MedicalDirector, Nurse |
| GET | `/patients` | List patients (filter by membership_id) | ClinicAdmin, IntakeNurse, MedicalDirector, Nurse |
| POST | `/memberships` | Create a membership/package | ClinicAdmin |
| GET | `/memberships/{id}` | Read a membership | ClinicAdmin, IntakeNurse, MedicalDirector |
| POST | `/memberships/{id}/suspend` | Suspend a membership | ClinicAdmin |
| POST | `/memberships/{id}/reinstate` | Reinstate a suspended membership | ClinicAdmin |
| GET | `/patients/{id}/memberships` | Reverse lookup: memberships of a patient | ClinicAdmin, IntakeNurse, MedicalDirector |
| POST | `/standing-orders` | Create a draft standing order | MedicalDirector |
| GET | `/standing-orders/{id}` | Read a standing order | ClinicAdmin, MedicalDirector |
| GET | `/standing-orders` | List standing orders | ClinicAdmin, MedicalDirector |
| POST | `/standing-orders/{id}/activate` | Activate a draft standing order | MedicalDirector |
| POST | `/standing-orders/{id}/revoke` | Revoke an active standing order | MedicalDirector |
| POST | `/nurses` | Register an RN | ClinicAdmin |
| GET | `/nurses/{id}` | Read an RN | ClinicAdmin, MedicalDirector, Nurse |
| GET | `/lounges/{id}/nurses` | Reverse lookup: RNs rostered to a lounge | ClinicAdmin, MedicalDirector |
| POST | `/lounges` | Create a lounge | ClinicAdmin |
| GET | `/lounges/{id}` | Read a lounge | ClinicAdmin, IntakeNurse, MedicalDirector, Nurse |
| POST | `/supply-lots` | Receive a supply lot | ClinicAdmin |
| GET | `/supply-lots/{id}` | Read a supply lot | ClinicAdmin, MedicalDirector, Nurse |
| GET | `/supply-lots` | List supply lots | ClinicAdmin, MedicalDirector, Nurse |
| POST | `/supply-lots/{id}/quarantine` | Quarantine a lot | ClinicAdmin |
| POST | `/dispatch-routes` | Create a mobile dispatch route | ClinicAdmin |
| GET | `/dispatch-routes/{id}` | Read a route | ClinicAdmin, MedicalDirector, Nurse |
| GET | `/nurses/{id}/dispatch-routes` | Reverse lookup: routes for a nurse | ClinicAdmin, MedicalDirector, Nurse |
| POST | `/dispatch-routes/{id}/lock` | Lock a route | ClinicAdmin |
| POST | `/dispatch-routes/{id}/close` | Close a locked route | ClinicAdmin |
| POST | `/appointments` | Request an appointment | ClinicAdmin, IntakeNurse |
| GET | `/appointments/{id}` | Read an appointment | ClinicAdmin, IntakeNurse, MedicalDirector, Nurse |
| GET | `/appointments` | List appointments | ClinicAdmin, IntakeNurse, MedicalDirector, Nurse |
| POST | `/appointments/{id}/intake` | Author and submit an intake screening | IntakeNurse |
| POST | `/appointments/{id}/schedule` | Schedule an appointment (forks on outcome) | ClinicAdmin |
| POST | `/appointments/{id}/md-approve` | Approve an MD-review appointment | MedicalDirector |
| POST | `/appointments/{id}/md-decline` | Decline an MD-review appointment | MedicalDirector |
| POST | `/appointments/{id}/dispatch` | Dispatch an RN to a scheduled appointment | ClinicAdmin |
| POST | `/appointments/{id}/start` | Start the infusion | Nurse |
| POST | `/appointments/{id}/complete` | Complete the infusion | Nurse |
| POST | `/appointments/{id}/cancel` | Cancel a non-terminal appointment | ClinicAdmin |
| GET | `/intake-screenings/{id}` | Read an intake screening | ClinicAdmin, IntakeNurse, MedicalDirector |
| GET | `/appointments/{id}/intake-screenings` | Reverse lookup: screenings for an appointment | ClinicAdmin, IntakeNurse, MedicalDirector |
| POST | `/consents` | Record patient consent | IntakeNurse, ClinicAdmin |
| GET | `/consents/{id}` | Read a consent | ClinicAdmin, IntakeNurse, MedicalDirector |
| POST | `/consents/{id}/revoke` | Revoke a signed consent | IntakeNurse, ClinicAdmin, MedicalDirector |
| GET | `/appointments/{id}/consents` | Reverse lookup: consents for an appointment | ClinicAdmin, IntakeNurse, MedicalDirector |
| POST | `/adverse-events` | Report an adverse reaction | Nurse, MedicalDirector |
| GET | `/adverse-events/{id}` | Read an adverse event | ClinicAdmin, MedicalDirector, Nurse |
| POST | `/adverse-events/{id}/review` | Move an event to under review | MedicalDirector |
| POST | `/adverse-events/{id}/resolve` | Resolve an event | MedicalDirector |
| GET | `/appointments/{id}/adverse-events` | Reverse lookup: adverse events for an appointment | ClinicAdmin, MedicalDirector, Nurse |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SCREENING_BLOCKED` | 409 Conflict |
| `ERR_CONSENT_MISSING` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_NO_STANDING_ORDER` | 409 Conflict |
| `ERR_SLOT_CONFLICT` | 409 Conflict |
| `ERR_SUPPLY_UNAVAILABLE` | 409 Conflict |
| `ERR_CREDIT_INSUFFICIENT` | 409 Conflict |
| `ERR_LOT_HAS_RESERVATIONS` | 409 Conflict |
| `ERR_CONSENT_NOT_AFFIRMED` | 422 Unprocessable Entity |
| `ERR_ROUTE_LOCKED` | 409 Conflict |
| `ERR_VALIDATION_PARAM` | 400 Bad Request |

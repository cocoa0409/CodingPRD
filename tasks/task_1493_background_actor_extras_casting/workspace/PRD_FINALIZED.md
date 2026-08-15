# Background Extras Casting API — Product Requirements Document

## 1. Introduction

A Central Casting–style background casting agency lives and dies by the shoot day. Every morning, dozens of background performers must be booked against casting calls whose union quotas are dictated by collective-bargaining agreements, checked into holding areas with minute-level time capture, paid under overtime and meal-penalty rules that differ between union and non-union performers, and vouchered to an external payroll company — all while no-shows trigger a replacement pipeline that must refill a vacated union slot with a union standby before the camera rolls. This document specifies the API through which the agency operates that pipeline end to end: productions and their compliance standing, the background actor roster, casting calls with wardrobe and look requirements, day-player bookings, standby pools and replacement cases, shoot-day time events, pay vouchers with bump adjustments, and payroll batch submission with acknowledgment.

All casting-domain resources are mounted under `/central-casting`; a single operator-only logical-clock utility lives outside that prefix. Six roles participate — platform administrators, casting directors, casting associates, the background actors themselves, payroll coordinators, and union representatives — with deliberate segregation of duties around money-moving decisions. The specification below is written so that an engineer can implement the full service from this document alone: §2 fixes the system-wide contracts, §3 narrates the business workflows in which every rule lives, and §4–§5 provide the endpoint and error reference tables.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their capacity. A request missing either header, or presenting a role name the system does not recognize, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes exactly six roles, spelled as follows: `AgencyAdmin`, `CastingDirector`, `CastingAssociate`, `BackgroundActor`, `PayrollCoordinator`, and `UnionRepresentative`. Each operation restricts which roles may invoke it; a caller whose role is not on the endpoint's authorized list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `BackgroundActor`, `X-User-ID` is the `id` of the acting BackgroundActor record; ownership checks on any resource that references a BackgroundActor — a booking's `actor_id`, the booking underlying a voucher, or a standby entry's `actor_id` — compare that foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403). When `X-User-Role` is `AgencyAdmin`, `CastingDirector`, `CastingAssociate`, `PayrollCoordinator`, or `UnionRepresentative`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `issued_by_user_id` on a voucher, `requested_by_user_id` on a bump adjustment or ratio waiver, or `submitted_by_user_id` on a payroll batch) but never compares it to any entity's `id`.

Two segregation-of-duties rules cut across roles. The operator who decides a bump adjustment must not be the operator who requested it, or the decision is rejected with `ERR_SOD_SELF_APPROVAL` (HTTP 403). The operator who records a payroll company's acknowledgment of a batch must not be the operator who submitted that batch, or the acknowledgment is rejected with `ERR_SOD_SELF_ACKNOWLEDGE` (HTTP 403). Both rules compare `X-User-ID` values, never entity ids.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter skips a number of items from the start of the result set and defaults to 0. Unless stated otherwise, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Audit Fields

Every primary resource — Production, BackgroundActor, CastingCall, HoldingArea, Booking, Voucher, BumpAdjustment, PayrollBatch, ReplacementCase, StandbyEntry, and RatioWaiver — carries a standard set of system-managed fields:

- `id` (string): a server-minted unique identifier, formatted as a UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that increments with every mutation of the resource, including mutations driven by cascades and system sweeps rather than by a direct client request.

Two resources are deliberately thinner. A LookRequirement is immutable once created, and a TimeEvent is an append-only ledger record; both carry only `id` and `created_at` — `updated_at` and `version` are absent from these two resources.

### 2.5. The Logical Clock

The server keeps a logical clock, and every time-dependent rule in this document — offer expiry, the no-show grace period, replacement deadlines, the shoot-date gate — is judged against that logical clock, never against wall-clock time. Before any client request touches it, the logical clock reads exactly 2026-08-01T00:00:00Z. An `AgencyAdmin` may advance it through the operator capability `POST /_clock/set_current_utc`, supplying the target instant in the request field `to_iso8601`; the response reports the clock's new reading in `current_utc`. Advancing the clock is not inert: the sweep that follows expires offers and replacement cases whose deadlines have passed, with the full cascade described in §3.4 and §3.5.

### 2.6. Slot Accounting, Union Ratios, and the Compliance Index

Casting calls sell seats, and the books must always balance. For every casting call, the invariant `union_slots` plus `nonunion_slots` equals `slots_available` plus the count of that call's bookings in `OFFERED`, `CONFIRMED`, `CHECKED_IN`, or `WRAPPED` holds after every request. Creating a booking — directly or through a replacement offer — consumes one slot; declining, cancelling, expiring, or marking a booking as a no-show releases one. The system recomputes `slots_available`, `union_bookings_active`, and `nonunion_bookings_active` after each such mutation; the two active counts tally bookings in those same four states, broken out by `slot_type`.

Union-ratio governance runs in two tenses. `required_union_slots` is the call's `union_slots` minus its `approved_waiver_reduction`. The projected side is live: `projected_union_count` recomputes on every booking mutation as the count of the call's union bookings in the four active states, and `projected_compliant` — whether that count reaches `required_union_slots` — is evaluated and stored at lock time as a frozen verdict that later booking changes do not alter. The actual side is measured once, at wrap: `actual_union_checkins` freezes as the count of union bookings in `CHECKED_IN` or `WRAPPED`, `actual_compliant` records whether that count reaches `required_union_slots`, and both stay null-free but immutable thereafter (`actual_compliant` itself is null until wrap). A count exactly equal to the requirement passes, in either tense.

Each production carries a `compliance_index` that starts at 100. Every casting call that wraps with `actual_compliant` false subtracts 15 from it, never driving it below zero. The index gates future publishing: a production whose `compliance_index` has fallen below 30 may not publish further calls, while an index of exactly 30 still passes.

### 2.7. Payroll Aggregation and Production Exposure

A payroll batch's totals are always derived, never stored as independent truths. A batch's `gross_total_cents` equals the sum of the `gross_total_cents` of the vouchers currently referencing it, and its `voucher_count` equals the number of those vouchers; both are recomputed after every membership change — an item add, an item removal, a voucher dispute that ejects it from the batch, an acknowledgment that rejects members, or a bump approval touching a batched voucher. One level up, each production's `payroll_exposure_cents` equals the sum of `gross_total_cents` across all of that production's payroll batches and is recomputed whenever any batch total changes; each such recomputation increments the production's `version`.

### 2.8. Money, Minutes, and Rounding Discipline

All monetary values are integer cents. Intermediate arithmetic may carry fractional cents, but each payable component of a voucher is rounded half up to whole cents on its own, and the components are then summed — the system never sums unrounded components and rounds once at the end. Durations are integer minutes, and all counts (slots, occupancies, strikes, penalties) are integers. Every threshold in §3 states its boundary behavior explicitly; where a rule says a boundary value passes, it passes, and where it says a boundary value rejects, it rejects.

### 2.9. Optimistic Concurrency Control

Exactly two write operations participate in optimistic concurrency control; no other endpoint accepts a version field.

Adding a voucher to a payroll batch requires the request to carry `expected_batch_version`, holding the batch `version` the client last observed. If the batch's current `version` has advanced past that value — because another add, a removal, a dispute ejection, a bump approval, or an acknowledgment touched it in the meantime — the add is rejected with `ERR_STALE_BATCH_VERSION` (HTTP 412), forcing the client to re-read the batch rather than build on a superseded view.

Recomputing and re-issuing a voucher requires the request to carry `expected_voucher_version`, holding the voucher `version` the client last observed. A mismatch with the voucher's current `version` is rejected with `ERR_STALE_VOUCHER_VERSION` (HTTP 412), since the adjustment would otherwise be based on a computation the client never saw.

### 2.10. The Validation Pipeline

Every write request is screened in a fixed order, and the first failing check produces the error response:

1. Header presence and role-name validity (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Role authorization for the endpoint (`ERR_FORBIDDEN_ROLE`).
3. Entity-backed ownership, where the caller is a `BackgroundActor` (`ERR_FORBIDDEN_OWNERSHIP`).
4. Segregation-of-duties checks on bump decisions and batch acknowledgment (`ERR_SOD_SELF_APPROVAL`, `ERR_SOD_SELF_ACKNOWLEDGE`).
5. Existence of every identifier appearing in the path or body, validated left to right, each miss producing that resource's not-found error: `ERR_PRODUCTION_NOT_FOUND`, `ERR_ACTOR_NOT_FOUND`, `ERR_CASTING_CALL_NOT_FOUND`, `ERR_LOOK_REQUIREMENT_NOT_FOUND`, `ERR_HOLDING_AREA_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_TIME_EVENT_NOT_FOUND`, `ERR_VOUCHER_NOT_FOUND`, `ERR_BUMP_ADJUSTMENT_NOT_FOUND`, `ERR_PAYROLL_BATCH_NOT_FOUND`, `ERR_REPLACEMENT_CASE_NOT_FOUND`, `ERR_STANDBY_ENTRY_NOT_FOUND`, or `ERR_RATIO_WAIVER_NOT_FOUND`.
6. Body schema: required fields present, enum members valid, integer ranges respected — slot counts at least zero, rates, capacities, bump amounts, and planned durations strictly positive, waiver reductions at least zero (`ERR_VALIDATION`).
7. The production-phase gate: planning-phase mutations (creating a casting call, publishing, adding look requirements, creating holding areas, registering standby entries, creating bookings) require the production `ACTIVE`, failing with `ERR_PRODUCTION_NOT_ACTIVE`; production wrap additionally requires every call of the production to be `WRAPPED` or `CANCELLED`, failing with `ERR_PRODUCTION_NOT_WRAPPABLE`; voucher and payroll-batch mutations accept a production that is `ACTIVE` or `WRAPPED`.
8. Entity state preconditions for the transition or creation at hand, including the create-time state gates: a booking requires its call `PUBLISHED`; a standby entry requires `PUBLISHED` or `LOCKED`; a look requirement requires `DRAFT`; a holding area requires `PUBLISHED` or `LOCKED`; a ratio waiver requires `DRAFT` or `PUBLISHED`; a time event requires its booking `CHECKED_IN` or `WRAPPED`; a bump requires its voucher `DRAFT`, `ISSUED`, `DISPUTED`, or `REJECTED`. Failures surface as `ERR_CALL_INVALID_STATE`, `ERR_CALL_NOT_ACCEPTING`, `ERR_BOOKING_INVALID_STATE`, `ERR_BOOKING_NOT_WRAPPED`, `ERR_VOUCHER_INVALID_STATE`, `ERR_BUMP_INVALID_STATE`, `ERR_BUMP_VOUCHER_LOCKED`, `ERR_BATCH_INVALID_STATE`, `ERR_CASE_INVALID_STATE`, `ERR_WAIVER_INVALID_STATE`, or `ERR_STANDBY_NOT_ACTIVE`.
9. Optimistic concurrency, on the two operations named in §2.9 (`ERR_STALE_BATCH_VERSION`, `ERR_STALE_VOUCHER_VERSION`).
10. Business rules, in this relative order: actor eligibility (`ERR_ACTOR_NOT_ELIGIBLE`); the compliance publish gate (`ERR_COMPLIANCE_INDEX_TOO_LOW`); shoot-date matching (`ERR_SHOOT_DATE_MISMATCH`); no-show timing (`ERR_NO_SHOW_TOO_EARLY`); the turnaround rest rule (`ERR_TURNAROUND_VIOLATION`); duplicate bookings and standby entries (`ERR_DUPLICATE_BOOKING`); slot availability (`ERR_NO_SLOT_AVAILABLE`, `ERR_NO_NONUNION_SLOT`); the union-ratio lock gate (`ERR_UNION_RATIO_SHORTFALL`); waiver reduction bounds (`ERR_WAIVER_REDUCTION_INVALID`); holding-area capacity (`ERR_HOLDING_AREA_FULL`); time-event sequencing (`ERR_TIME_EVENT_INVALID`); batch item consistency (`ERR_VOUCHER_NOT_SUBMITTABLE`); and batch non-emptiness (`ERR_BATCH_EMPTY`).

## 3. Business Logic & Workflows

### 3.1. Standing Up a Production and Managing the Actor Roster

Work begins when an `AgencyAdmin` registers a **Production** with its `title`, `studio_code`, and the `payroll_company_name` of the external payroll house that will eventually receive its batches. A new production sits in `SETUP` with a `compliance_index` of 100 and `payroll_exposure_cents` of zero, and nothing operational may happen under it until the administrator activates it: activation moves the production from `SETUP` to `ACTIVE` and increments its `version`, and attempting it on a production in any other state fails with `ERR_PRODUCTION_NOT_ACTIVE`.

The roster is the administrator's second responsibility. Registering a **BackgroundActor** captures the performer's `legal_name` for payroll, their `union_status` of `SAG_AFTRA` or `NONUNION`, an optional list of free-form `special_abilities` tags (horseback riding, ballroom dance, and the like), and an optional wardrobe `sizes` object. A registrant starts `REGISTERED` with a `no_show_count` of zero and a `reliability_score` of 100, and cannot be booked until an administrator verifies their paperwork, moving them `REGISTERED` → `ELIGIBLE`; verifying anyone not currently `REGISTERED` fails with `ERR_ACTOR_NOT_ELIGIBLE`.

Discipline runs in the opposite direction. An administrator may suspend an `ELIGIBLE` actor, moving them to `SUSPENDED` — and the system does the same automatically the moment an actor's `no_show_count` reaches exactly 3 through the no-show pipeline of §3.4. Either way the suspension cascade is identical: every booking the actor still holds in `OFFERED` moves to `EXPIRED`, every booking in `CONFIRMED` moves to `CANCELLED`, each of those releases its slot back to its casting call, every `ACTIVE` standby entry of the actor moves to `WITHDRAWN`, and the actor's `version` increments. Suspending an actor who is not `ELIGIBLE` fails with `ERR_ACTOR_NOT_ELIGIBLE`. An administrator may later reinstate a `SUSPENDED` actor, which returns them to `ELIGIBLE`, resets `no_show_count` to zero, recomputes `reliability_score` to 100, and increments `version`.

The reliability score itself is the arithmetic of trust: one hundred minus twenty points per lifetime no-show, never dropping below zero. It is recomputed on every no-show and on every reinstatement, and §3.5 shows it deciding who gets offered a vacated slot first.

A production's life ends with the wrap. A `CastingDirector` may wrap an `ACTIVE` production — wrapping from any other state fails with `ERR_PRODUCTION_NOT_ACTIVE` — but only once every casting call belonging to it has reached `WRAPPED` or `CANCELLED`; if any call is still live, the wrap is rejected with `ERR_PRODUCTION_NOT_WRAPPABLE`. A successful wrap moves the production to `WRAPPED`, expires any still-`ACTIVE` standby entries across its calls, and increments its `version`. `WRAPPED` is terminal for the production, though payroll work on its vouchers and batches continues as §3.8 describes.

### 3.2. Designing the Call: Look Requirements, Holding Areas, and Ratio Waivers

A `CastingDirector` authors a **CastingCall** inside an `ACTIVE` production by naming the `production_id` and supplying the shoot day's `shoot_date` as an ISO calendar date, the `general_call_time` that bookings will default to, the planned `scheduled_duration_minutes` of the workday, the `location`, the planned headcounts `union_slots` and `nonunion_slots`, the daily base rates `union_rate_cents` and `nonunion_rate_cents`, and optional free-form `wardrobe_notes`. The call is born in `DRAFT`, its computed slot and ratio fields initialize with `slots_available` equal to the two headcounts combined, `approved_waiver_reduction` at zero, `actual_union_checkins` at zero, and `actual_compliant` null until the day the call wraps.

While the call is still `DRAFT`, the director may attach **LookRequirement** records describing what performers must bring or supply: a `casting_call_id`, a `category` drawn from `WARDROBE_OWN`, `FORMAL_WEAR`, `PERIOD_COSTUME`, `HAIR_MAKEUP`, `PROPS_OWN`, or `SPECIAL_ABILITY`, a free-text `description` such as "1920s tuxedo, actor-provided", a strictly positive suggested `bump_amount_cents`, and a `mandatory` flag that defaults to false. Once the call leaves `DRAFT` the look list is frozen; attempting to add a requirement to a call in any later state fails with `ERR_CALL_INVALID_STATE`.

Holding areas come later in planning. A `CastingAssociate` may create a **HoldingArea** — a `name` like "Basecamp A" and a strictly positive `capacity` — only while the call is `PUBLISHED` or `LOCKED`; the new area starts with `current_occupancy` zero, and attempts against a call in any other state fail with `ERR_CALL_INVALID_STATE`.

When a production cannot realistically field the planned union headcount, the director files a **RatioWaiver** against a call in `DRAFT` or `PUBLISHED`, supplying the `casting_call_id`, a `union_slot_reduction` of zero or more, and a `justification`. The request enters `REQUESTED` with `requested_by_user_id` taken from the caller's header. A reduction exceeding the call's `union_slots` is rejected with `ERR_WAIVER_REDUCTION_INVALID` (HTTP 422), and filing against a call in a later state fails with `ERR_CALL_INVALID_STATE`. A `UnionRepresentative` then decides: denying a `REQUESTED` waiver moves it to `DENIED`, while approving one requires the call to still be `DRAFT` or `PUBLISHED` and requires that no other waiver for the call already stands `APPROVED` — a second approval is rejected with `ERR_VALIDATION`. Approval stamps `decided_by_user_id` from the representative's header, writes the waiver's `union_slot_reduction` onto the call as its `approved_waiver_reduction`, recomputes `required_union_slots`, and increments the call's `version` alongside the waiver's own. Deciding a waiver no longer `REQUESTED` fails with `ERR_WAIVER_INVALID_STATE`. If the call is later cancelled, any still-`REQUESTED` waiver moves to `REVOKED` automatically.

### 3.3. Booking Day Players and Locking the Union Ratio

Publishing is the call's first gate, and its checks run in a fixed order: the combined headcount `union_slots` plus `nonunion_slots` must exceed zero, failing with `ERR_VALIDATION`; the production must be `ACTIVE`, failing with `ERR_PRODUCTION_NOT_ACTIVE`; the call itself must still be `DRAFT`, failing with `ERR_CALL_INVALID_STATE`; and the production's `compliance_index` must be at least 30 — exactly 30 passes — failing with `ERR_COMPLIANCE_INDEX_TOO_LOW`. A published call accepts bookings.

A `CastingAssociate` books a day player by submitting the `casting_call_id`, the `actor_id`, and optionally a per-booking `call_time` that overrides the call's `general_call_time` when supplied. The offer is validated as a chain, in this order: the production must be `ACTIVE`; the call must be `PUBLISHED` (`ERR_CALL_INVALID_STATE` otherwise); the actor must be `ELIGIBLE` (`ERR_ACTOR_NOT_ELIGIBLE`); the turnaround rest rule must hold (`ERR_TURNAROUND_VIOLATION`); the actor must not already hold another booking of this call in `OFFERED`, `CONFIRMED`, or `CHECKED_IN` (`ERR_DUPLICATE_BOOKING`); and a slot must be available under the union eligibility rules below. A created booking enters `OFFERED` with its economics snapshotted: `slot_type` records `UNION` for a `SAG_AFTRA` actor and `NONUNION` otherwise, and `daily_rate_cents` copies the call's `union_rate_cents` or `nonunion_rate_cents` to match. Later edits to rates or to the actor's union status never retro-change an existing booking. The booking's `expected_wrap_time` is its `call_time` plus the call's `scheduled_duration_minutes`, and for an ordinary booking its `offer_expires_at` equals its `call_time` — an offer the actor never answers dies at call time. The creation consumes one slot: `slots_available` drops by one, the active counts recompute, and the call's `version` increments. The two replacement-linkage fields, `replacement_case_id` and `replaces_booking_id`, stay null on ordinary bookings, and `is_replacement` is false.

The turnaround rule protects performers from back-to-back days. The new booking's half-open window — from its `call_time` up to but not including its `expected_wrap_time` — is compared against every other booking the actor holds in `OFFERED`, `CONFIRMED`, `CHECKED_IN`, or `WRAPPED` across all calls. For each, at least 600 minutes — ten hours — of rest must separate the two windows in one direction or the other: either the new booking starts no earlier than ten hours after the other booking's window ends, or the other booking starts no earlier than ten hours after the new booking's window ends. A gap of exactly ten hours is permitted; overlap, or a shorter gap, rejects the create with `ERR_TURNAROUND_VIOLATION`. For a comparison booking already `WRAPPED`, its voucher's `wrap_out_at` stands in for `expected_wrap_time` whenever the voucher has one.

Slot availability itself discriminates by union status. Let the consumed total be `union_bookings_active` plus `nonunion_bookings_active`. A union actor may be booked whenever that consumed total is still below the call's combined headcount — union performers may spill into nominally non-union seats — and is otherwise rejected with `ERR_NO_SLOT_AVAILABLE`. A non-union actor faces a double gate: `nonunion_bookings_active` must remain below `nonunion_slots` plus the call's `approved_waiver_reduction`, and the consumed total must remain below the combined headcount; failure yields `ERR_NO_NONUNION_SLOT`.

The actor answers for themselves. Accepting requires the caller to own the booking (`ERR_FORBIDDEN_OWNERSHIP`), the booking to be `OFFERED` (`ERR_BOOKING_INVALID_STATE`), and the acceptance window to be open: an ordinary booking may be accepted only while its call is `PUBLISHED`, and a replacement booking only while its call is `SHOOTING`; any other combination fails with `ERR_CALL_NOT_ACCEPTING`. Acceptance moves the booking `OFFERED` → `CONFIRMED`, and when the booking is a replacement it additionally moves the owning replacement case to `FILLED` and the actor's standby entry for that call to `PROMOTED`. Declining the offer moves the booking to `DECLINED`, releases its slot — `slots_available` rises by one, the union and non-union active counts recompute, and the call's `version` increments — and, for a replacement, returns the owning case to `OPEN`, appends the actor to the case's `excluded_actor_ids`, and clears the case's `offered_booking_id` and `offered_actor_id`. Should the logical clock pass a booking's `offer_expires_at` while it is still `OFFERED`, the sweep moves it to `EXPIRED` with the same slot release; a replacement offer that dies this way reopens its case to `OPEN` if the clock has not yet passed the case's `deadline_at`, or moves the case to `EXPIRED` if it has, excluding the actor and clearing the offered fields either way. An associate may also cancel a booking outright — cancelling carries an optional `reason` — from `OFFERED` or `CONFIRMED` (`ERR_BOOKING_INVALID_STATE` from any other state), releasing the slot; a replacement cancelled while its case is still `CANDIDATE_OFFERED` sends the case back to `OPEN` with the actor excluded. Cancelling a `CONFIRMED` booking while the call is `SHOOTING` is a shoot-day emergency and opens a replacement case with `reason` `CANCELLATION`, as §3.5 details.

Once the director is satisfied with the book, locking freezes the projection. Locking requires the call to be `PUBLISHED` and the live `projected_union_count` to reach `required_union_slots` — exactly equal passes — and a shortfall is rejected with `ERR_UNION_RATIO_SHORTFALL` (HTTP 422). Success moves the call `PUBLISHED` → `LOCKED` and stores `projected_compliant` as true; that stored verdict is a snapshot and does not move with later booking mutations, even if a subsequent no-show hollows out the union contingent it certified.

A director may cancel the call itself from `DRAFT`, `PUBLISHED`, or `LOCKED` — from any later state the attempt fails with `ERR_CALL_INVALID_STATE` — optionally supplying a `reason`. Cancellation moves the call to `CANCELLED`, moves every booking still `OFFERED` or `CONFIRMED` to `CANCELLED` with each releasing its slot, moves every `ACTIVE` standby entry to `EXPIRED`, revokes every `REQUESTED` ratio waiver to `REVOKED`, and increments the call's `version`.

### 3.4. Shoot Day: Call Times, Holding, Time Events, and No-Shows

The shoot day opens when a `CastingAssociate` starts shooting. The call must be `LOCKED` (`ERR_CALL_INVALID_STATE` otherwise), and the logical clock's calendar date must equal the call's `shoot_date`, failing with `ERR_SHOOT_DATE_MISMATCH`; success moves the call `LOCKED` → `SHOOTING`.

Check-in is the associate's first floor duty. It requires the booking `CONFIRMED` (`ERR_BOOKING_INVALID_STATE`), the call `SHOOTING` (`ERR_CALL_INVALID_STATE`), and the actor still `ELIGIBLE` (`ERR_ACTOR_NOT_ELIGIBLE`). The associate may supply a `holding_area_id`; when supplied, the area must belong to this call — a foreign or missing area fails with `ERR_HOLDING_AREA_NOT_FOUND` — and its `current_occupancy` must be strictly below its `capacity`, since occupancy equal to capacity rejects the check-in with `ERR_HOLDING_AREA_FULL`. A successful check-in moves the booking `CONFIRMED` → `CHECKED_IN`, appends a `CHECK_IN` TimeEvent stamped at the logical clock, automatically creates the booking's **Voucher** in `DRAFT` — exactly one voucher per booking, for its whole life — and, when a holding area was named, raises that area's `current_occupancy` by one and increments the area's `version`.

Time capture thereafter is an append-only ledger of **TimeEvent** records, each carrying its `booking_id`, an `event_type` of `CHECK_IN`, `MEAL_OUT`, `MEAL_IN`, or `WRAP_OUT`, an `occurred_at` instant in the logical past or present, and a `recorded_by` taken from the recording associate's header. The check-in and wrap-out actions append their own events automatically; associates additionally append manual events — meal breaks, and corrections — against a booking that is `CHECKED_IN` or `WRAPPED` (any other booking state fails with `ERR_BOOKING_INVALID_STATE`). The ledger polices its own sequence, rejecting violations with `ERR_TIME_EVENT_INVALID`: no event may precede the check-in; there must be exactly one effective `CHECK_IN`; at most one effective `WRAP_OUT` may exist and it must follow the check-in; a `MEAL_IN` requires a preceding `MEAL_OUT` that no other `MEAL_IN` has yet matched; and a manually submitted `WRAP_OUT` is always rejected, because wrap-out flows only through the wrap-out action. Corrections chain: an event may name a `corrects_event_id` referencing an as-yet-uncorrected event of the same booking (a missing or foreign target fails with `ERR_TIME_EVENT_NOT_FOUND`; an invalid correction fails with `ERR_TIME_EVENT_INVALID`), superseding it without erasing it. Notably, appending events does not recompute the voucher — money moves only at issue and adjust time, per §3.6.

The saddest booking transition is the no-show. An associate may mark it only while the booking is `CONFIRMED` (`ERR_BOOKING_INVALID_STATE`), the call is `SHOOTING` (`ERR_CALL_INVALID_STATE`), and the logical clock has reached at least sixty minutes past the booking's `call_time`; earlier attempts fail with `ERR_NO_SHOW_TOO_EARLY`. The mark ripples outward in a two-hop cascade. First, the call releases the slot — `slots_available` rises by one, the projected and active union counts recompute, and the call's `version` increments — and a **ReplacementCase** springs into existence in `OPEN` with `reason` `NO_SHOW`, its `required_slot_type` copied from the vacated booking's `slot_type`, and its `deadline_at` set to the booking's `call_time` plus 120 minutes. Simultaneously, the actor's `no_show_count` increments by one, `reliability_score` recomputes, and the actor's `version` increments. Second, if that increment brings the count to exactly 3, the actor auto-transitions `ELIGIBLE` → `SUSPENDED` with the full suspension cascade of §3.1 — outstanding offers expire, confirmed bookings cancel, standby entries withdraw. The booking itself lands in `NO_SHOW`, terminal.

Wrapping a performer out requires the booking `CHECKED_IN` and the call `SHOOTING`, with the same `ERR_BOOKING_INVALID_STATE` and `ERR_CALL_INVALID_STATE` guards. Wrap-out moves the booking `CHECKED_IN` → `WRAPPED`, appends a `WRAP_OUT` TimeEvent at the logical clock, and releases the holding seat — the area's `current_occupancy` drops by one and its `version` increments — when the booking had one.

The call itself wraps last. Its associate may wrap a `SHOOTING` call only when every booking has reached a terminal state — `WRAPPED`, `DECLINED`, `EXPIRED`, `CANCELLED`, or `NO_SHOW` — and every replacement case sits in `FILLED` or `EXPIRED`; any straggler fails with `ERR_CALL_INVALID_STATE`. Wrapping freezes the actuals: `actual_union_checkins` records the count of union bookings in `CHECKED_IN` or `WRAPPED` at that instant (the terminal-state precondition means none remain checked in in practice), and `actual_compliant` records whether that count reaches `required_union_slots`, exactly equal passing. A call that wraps non-compliant costs the production fifteen points of `compliance_index`, floored at zero, and increments the production's `version`. Remaining `ACTIVE` standby entries move to `EXPIRED`, and the call's own `version` increments as it settles into `WRAPPED`.

### 3.5. The Standby Pool and the Replacement Pipeline

Prudent associates staff a bench before it is needed. Registering a **StandbyEntry** names a `casting_call_id` and an `actor_id`, and requires the call `PUBLISHED` or `LOCKED` (`ERR_CALL_INVALID_STATE` otherwise), the production `ACTIVE`, and the actor `ELIGIBLE` (`ERR_ACTOR_NOT_ELIGIBLE`); an actor who already holds an `ACTIVE` entry on that call may not be registered twice (`ERR_DUPLICATE_BOOKING`). The entry is born `ACTIVE` with its `slot_type` snapshotted from the actor's union status at registration. An entry leaves the pool in three ways: the owning actor or an associate may withdraw it — an actor caller must own the entry (`ERR_FORBIDDEN_OWNERSHIP`), and only an `ACTIVE` entry may be withdrawn, otherwise `ERR_STANDBY_NOT_ACTIVE` — moving it to `WITHDRAWN`; the system moves it to `PROMOTED` when its actor confirms a replacement booking for the call; and it moves to `EXPIRED` when its call wraps or is cancelled.

A **ReplacementCase** is the system's answer to a shoot-day vacancy, created automatically by a mark-no-show (reason `NO_SHOW`) or by the shoot-day cancellation of a `CONFIRMED` booking (reason `CANCELLATION`). The case records its `casting_call_id`, the `original_booking_id` that vacated the seat, a `required_slot_type` copied from the vacated booking's snapshot, and a `deadline_at` two hours after the original booking's `call_time`. Its `excluded_actor_ids` list begins empty, `offered_booking_id` and `offered_actor_id` begin null, and `attempts_count` begins at zero.

Working a case is a negotiation of rounds. When an associate requests the next offer, the case must be `OPEN` (`ERR_CASE_INVALID_STATE` otherwise) and the call must be `SHOOTING` (`ERR_CALL_INVALID_STATE` otherwise). The selection filter is conjunctive — a candidate must satisfy all five conditions: an `ACTIVE` standby entry on this call; entry `slot_type` matching the case's `required_slot_type`; an actor currently `ELIGIBLE`; an actor not listed in the case's `excluded_actor_ids`; and an actor holding no booking in `OFFERED`, `CONFIRMED`, or `CHECKED_IN` on this call. Survivors rank by `reliability_score`, highest first, with ties broken by the standby entry's `created_at`, earliest first — never by identifier. If no candidate survives, the case slides `OPEN` → `EXPIRED`, the request still succeeds with HTTP 200, and no booking is created. Otherwise the top candidate receives a freshly created booking in `OFFERED`: `is_replacement` true, `replacement_case_id` pointing at the case, `replaces_booking_id` pointing at the vacated booking, `call_time` inherited from that original booking, rate and slot snapshots taken as at any creation, `offer_expires_at` set to the case's `deadline_at` rather than to call time, and one slot consumed — `slots_available` drops by one and the call's `version` increments. The case itself moves to `CANDIDATE_OFFERED`, records the new booking and actor in `offered_booking_id` and `offered_actor_id`, and raises `attempts_count` by one.

From `CANDIDATE_OFFERED` the case resolves through the candidate's answer. An acceptance fills it: the booking's `OFFERED` → `CONFIRMED` transition moves the case to `FILLED` and the promoted actor's standby entry to `PROMOTED`. A decline or an offer expiry returns the case to `OPEN`, appends that actor to `excluded_actor_ids` so they are never re-offered this case, and clears the offered fields — ready for another round, until the deadline runs out. And the clock can end things two ways: sweeping past `deadline_at` while an offer stands outstanding expires both the offer booking (releasing its slot) and the case itself, while an associate may also expire an `OPEN` case manually — expiring from any other state fails with `ERR_CASE_INVALID_STATE`. `FILLED` and `EXPIRED` are terminal.

### 3.6. The Voucher: Event Replay, Overtime, and Meal Penalties

Every booking that checks in already owns its **Voucher**, created automatically in `DRAFT` at check-in and bound one-to-one to the booking; its `payroll_batch_id` starts null, and its computed fields wait for issuance. Issuing is the associate's act of turning a wrapped day into money: it requires the voucher `DRAFT` (`ERR_VOUCHER_INVALID_STATE`) and the booking `WRAPPED` (`ERR_BOOKING_NOT_WRAPPED`), and it computes and stores every pay field at once.

The computation begins with the timeline. The effective event set takes all of the booking's time events and excludes any event that another event's `corrects_event_id` supersedes; a correction is itself effective unless a later correction supersedes it in turn, so chains of corrections resolve to their last link. Effective events are ordered by `occurred_at` ascending, ties broken by `created_at` ascending. From that ordered stream, `check_in_at` is the `occurred_at` of the first effective `CHECK_IN`, `wrap_out_at` is the `occurred_at` of the last effective `WRAP_OUT`, and meals are the consecutive pairs of a `MEAL_OUT` followed by its matching `MEAL_IN`.

Elapsed and net time come next, in a pinned evaluation order that keeps meal timeliness independent of deductions. `gross_elapsed_minutes` is the difference between `wrap_out_at` and `check_in_at` in minutes. Meal timeliness is judged on gross elapsed time, never on net: the first meal is timely when its `MEAL_OUT` occurs no more than 360 minutes — six hours — after check-in, and each later meal is timely when its `MEAL_OUT` occurs no more than 360 minutes after the previous meal's `MEAL_IN`; a meal beginning at exactly the 360-minute mark counts as timely. `meal_penalty_count` tallies the out-of-window meals, adds one further violation when the gross elapsed time exceeds 360 minutes and no meal was taken at all, and caps the total at 3 violations. `net_work_minutes` then subtracts from the gross elapsed time the durations of the timely meals only — a penalized meal remains paid time and is not deducted.

Wages follow the union contract's two tiers, computed from an hourly rate of the booking's `daily_rate_cents` divided by eight — the daily rate buys an eight-hour day — with fractional cents permitted at this intermediate step. Let n be `net_work_minutes`. For a union booking, regular minutes are the smaller of n and 480; first-tier overtime minutes are the portion of n beyond 480, capped at 120; second-tier overtime minutes are the portion of n beyond 600. For a non-union booking the regular portion is likewise capped at 480, but first-tier overtime runs to a cap of 240 minutes and second-tier accrues only beyond 720 minutes. The voucher stores these splits as `ot_tier1_minutes` and `ot_tier2_minutes` alongside `net_work_minutes`.

Rounding is per component, then summed. `base_wages_cents` is the regular minutes divided by sixty and multiplied by the hourly rate, rounded half up to whole cents. `ot_wages_cents` is the sum of two independently rounded components: first-tier minutes divided by sixty, multiplied by the hourly rate and by one and a half, rounded half up; plus second-tier minutes divided by sixty, multiplied by the hourly rate and by two, rounded half up. `meal_penalty_cents` is half the hourly rate, rounded half up to whole cents, multiplied by `meal_penalty_count`. `bumps_total_cents` is the sum of `amount_cents` across the voucher's `APPROVED` bump adjustments — pending claims do not yet count. Finally, `gross_total_cents` is the sum of those four rounded figures. Issuance also stamps `issued_by_user_id` from the caller's header and `issued_at` from the logical clock, moves the voucher `DRAFT` → `ISSUED`, and increments its `version`.

Before the day is even wrapped, anyone may peek at the money. The voucher's estimate — available in any state before `PAID` — is forward-looking: it substitutes the scheduled wrap (the booking's `call_time` plus the call's `scheduled_duration_minutes`) for actual events, assumes exactly one timely thirty-minute meal, so the scheduled net is `scheduled_duration_minutes` minus 30 and never below zero, runs the same tier formula with `meal_penalty_count` zero, and counts both `PENDING` and `APPROVED` bumps in its bump total, with the same per-component rounding. The estimate response reports `estimated_gross_cents` and `estimated_net_work_minutes`, plus a `bump_basis` string recording which bump states were counted.

Corrections after issuance travel one of two roads. The performer themselves may dispute an `ISSUED` voucher — the caller must own the underlying booking (`ERR_FORBIDDEN_OWNERSHIP`), and disputing from any other voucher state fails with `ERR_VOUCHER_INVALID_STATE`; the dispute may carry an optional `reason`. A dispute moves the voucher to `DISPUTED` and, when the voucher currently sits in an `OPEN` batch, ejects it: `payroll_batch_id` is cleared, the batch's `gross_total_cents` and `voucher_count` recompute, the batch's `version` increments, and the production's `payroll_exposure_cents` recomputes with its own `version` increment. The associate's road is the adjustment, which recomputes the final gross over the current effective events and the current `APPROVED` bumps and re-issues the voucher: it is permitted from `ISSUED`, `DISPUTED`, or `REJECTED` (any other state fails with `ERR_VOUCHER_INVALID_STATE`), requires the OCC guard of §2.9 — a stale `expected_voucher_version` fails with `ERR_STALE_VOUCHER_VERSION` — may carry an optional `note`, stamps `adjusted_by_user_id`, returns the voucher to `ISSUED`, and increments its `version` by exactly one. The remaining transitions belong to the payroll pipeline of §3.8: batch submission moves member vouchers `ISSUED` → `SUBMITTED`, and the payroll company's acknowledgment moves each `SUBMITTED` voucher to `PAID` — terminal — or to `REJECTED`, which also ejects it from the batch and clears its `payroll_batch_id`.

### 3.7. Bump Adjustments Under Segregation of Duties

Wardrobe owned, formal wear, period costume, hair and makeup, personal props, special abilities — the work that earns extra money is claimed through a **BumpAdjustment**. A `CastingAssociate` files the claim against a voucher by naming the `voucher_id`, a `category` from the same six-value enumeration used by look requirements, a strictly positive `amount_cents`, and an optional free-text `justification`. The voucher must be in `DRAFT`, `ISSUED`, `DISPUTED`, or `REJECTED`; once a voucher is `SUBMITTED` or `PAID` it is locked, and filing fails with `ERR_BUMP_VOUCHER_LOCKED`. The new adjustment enters `PENDING` with `requested_by_user_id` captured from the filing associate's header.

Decisions belong to a `CastingDirector`, and never to the requester: both approval and rejection compare the decider's `X-User-ID` against `requested_by_user_id` and refuse self-adjudication with `ERR_SOD_SELF_APPROVAL`, and both require the adjustment still `PENDING` (`ERR_BUMP_INVALID_STATE` otherwise). Approval additionally re-checks the voucher lock — approving against a `SUBMITTED` or `PAID` voucher fails with `ERR_BUMP_VOUCHER_LOCKED` — and stamps `decided_by_user_id`. An approval against an `ISSUED` voucher immediately recomputes that voucher's `bumps_total_cents` and `gross_total_cents` and increments the voucher's `version`; when that voucher sits in an `OPEN` batch, the cascade continues — the batch's `gross_total_cents` recomputes, the batch's `version` increments, and the production's `payroll_exposure_cents` recomputes. Rejection simply settles the adjustment at `REJECTED`. `APPROVED` and `REJECTED` are both terminal.

### 3.8. Payroll Batches: Assembly, Submission, and Acknowledgment

The payroll cycle is the last workflow standing, and it tolerates a wrapped production: vouchers and batches accept a production in `ACTIVE` or `WRAPPED`, failing with `ERR_PRODUCTION_NOT_ACTIVE` against anything else. A `PayrollCoordinator` opens a **PayrollBatch** by naming its `production_id` and a human `period_label` such as "2026-W33"; the batch starts `OPEN` with `gross_total_cents` zero and `voucher_count` zero.

Assembly is voucher by voucher. Adding an item names the `voucher_id` and carries the OCC guard of §2.9 — a stale `expected_batch_version` fails with `ERR_STALE_BATCH_VERSION`. The voucher itself must be `ISSUED`, must carry a null `payroll_batch_id`, and must belong to the same production as the batch; any violation fails with `ERR_VOUCHER_NOT_SUBMITTABLE`. A successful add points the voucher's `payroll_batch_id` at the batch, recomputes the batch totals, recomputes the production's `payroll_exposure_cents`, and increments the batch's `version` by one. The batch must be `OPEN` or `PARTIALLY_REJECTED` — any other state fails with `ERR_BATCH_INVALID_STATE` — and adding into a `PARTIALLY_REJECTED` batch deliberately returns it to `OPEN` for re-editing, incrementing `version`. Removal is the compensating mirror: removing an item from an `OPEN` batch clears the voucher's `payroll_batch_id`, recomputes batch totals and production exposure, and increments the batch's `version`.

Submission hands the batch to the external payroll company named on the production. The coordinator may submit from `OPEN` or `PARTIALLY_REJECTED` (`ERR_BATCH_INVALID_STATE` otherwise), the production must be `ACTIVE` or `WRAPPED` (`ERR_PRODUCTION_NOT_ACTIVE`), and the batch must hold at least one voucher — an empty submission fails with `ERR_BATCH_EMPTY` (HTTP 422). Membership is kept clean by construction: every voucher in a submittable batch is `ISSUED`, because dispute ejects members and only `ISSUED` vouchers may enter. Submission moves every member voucher `ISSUED` → `SUBMITTED`, incrementing each voucher's `version`, stamps `submitted_by_user_id` from the coordinator's header and `submitted_at` from the logical clock, and moves the batch to `SUBMITTED`.

The payroll company's answer arrives as an acknowledgment, recorded by a coordinator who must not be the operator named in `submitted_by_user_id` — self-acknowledgment fails with `ERR_SOD_SELF_ACKNOWLEDGE` — and only against a `SUBMITTED` batch (`ERR_BATCH_INVALID_STATE`). The request carries an `outcome` and, when that outcome is `REJECTED`, a `rejected_voucher_ids` list. An `ACCEPTED` outcome with an empty rejection list moves the batch to `ACKNOWLEDGED` — terminal — and every member voucher to `PAID`, incrementing each voucher's `version`. A `REJECTED` outcome with a non-empty list first verifies that every listed id is a `SUBMITTED` member of this batch (`ERR_VOUCHER_NOT_SUBMITTABLE` otherwise), then moves the listed vouchers to `REJECTED`, ejects them from the batch with their `payroll_batch_id` cleared, recomputes the batch's `gross_total_cents` and `voucher_count`, recomputes the production's `payroll_exposure_cents`, and lands the batch in `PARTIALLY_REJECTED`. Either way `acknowledged_by_user_id` is stamped and the batch's `version` increments. Rejected vouchers re-enter the associate's world: an adjustment can recompute and re-issue them, after which they may be re-added — which returns the batch from `PARTIALLY_REJECTED` to `OPEN` — and the cycle closes with a resubmission.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, and all read operations, return `200 OK`. List endpoints accept `limit` and `offset` plus the resource-specific filters noted in §3 — `production_id`, `shoot_date`, `status`, `union_status`, `category`, `casting_call_id`, `actor_id`, `booking_id`, `event_type`, `corrects_event_id`, `holding_area_id`, `replacement_case_id`, `replaces_booking_id`, `original_booking_id`, `voucher_id`, and `payroll_batch_id` — each narrowing the result set to matching rows. Request and response payloads for every operation are governed by the narratives of §3; this table is an index, not a schema.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/central-casting/productions` | Create a production | AgencyAdmin |
| GET | `/central-casting/productions` | List productions | All roles |
| GET | `/central-casting/productions/{id}` | Get a production | All roles |
| POST | `/central-casting/productions/{id}/activate` | Activate a production (SETUP → ACTIVE) | AgencyAdmin |
| POST | `/central-casting/productions/{id}/wrap` | Wrap a production; expires remaining standby entries | CastingDirector |
| POST | `/central-casting/actors` | Register a background actor | AgencyAdmin |
| GET | `/central-casting/actors` | List actors | All roles |
| GET | `/central-casting/actors/{id}` | Get an actor | All roles |
| POST | `/central-casting/actors/{id}/verify` | Verify paperwork (REGISTERED → ELIGIBLE) | AgencyAdmin |
| POST | `/central-casting/actors/{id}/suspend` | Suspend an actor; cancels bookings, withdraws standby entries | AgencyAdmin |
| POST | `/central-casting/actors/{id}/reinstate` | Reinstate a suspended actor; resets strike counters | AgencyAdmin |
| POST | `/central-casting/casting-calls` | Create a casting call in DRAFT | CastingDirector |
| GET | `/central-casting/casting-calls` | List casting calls | All roles |
| GET | `/central-casting/casting-calls/{id}` | Get a casting call | All roles |
| POST | `/central-casting/casting-calls/{id}/publish` | Publish a call; gates on production state and compliance index | CastingDirector |
| POST | `/central-casting/casting-calls/{id}/lock` | Lock a call; enforces and freezes the projected union ratio | CastingDirector |
| POST | `/central-casting/casting-calls/{id}/start-shooting` | Start the shoot day; logical date must equal the shoot date | CastingAssociate |
| POST | `/central-casting/casting-calls/{id}/wrap` | Wrap a call; freezes actual ratio and levies compliance penalty | CastingAssociate |
| POST | `/central-casting/casting-calls/{id}/cancel` | Cancel a call; cancels bookings, expires standby, revokes waivers | CastingDirector |
| POST | `/central-casting/look-requirements` | Add a wardrobe/look requirement to a DRAFT call | CastingDirector |
| GET | `/central-casting/look-requirements` | List look requirements | All roles |
| GET | `/central-casting/look-requirements/{id}` | Get a look requirement | All roles |
| POST | `/central-casting/holding-areas` | Create a holding area for a PUBLISHED or LOCKED call | CastingAssociate |
| GET | `/central-casting/holding-areas` | List holding areas | All roles |
| GET | `/central-casting/holding-areas/{id}` | Get a holding area | All roles |
| POST | `/central-casting/bookings` | Create a day-player booking in OFFERED; consumes a slot | CastingAssociate |
| GET | `/central-casting/bookings` | List bookings | All roles |
| GET | `/central-casting/bookings/{id}` | Get a booking | All roles |
| POST | `/central-casting/bookings/{id}/accept` | Accept an offer (owner actor); fills the case for replacements | BackgroundActor |
| POST | `/central-casting/bookings/{id}/decline` | Decline an offer (owner actor); releases the slot | BackgroundActor |
| POST | `/central-casting/bookings/{id}/cancel` | Cancel an offered or confirmed booking; shoot-day cancels open a case | CastingAssociate |
| POST | `/central-casting/bookings/{id}/check-in` | Check in a confirmed booking; optional holding-area assignment | CastingAssociate |
| POST | `/central-casting/bookings/{id}/mark-no-show` | Mark a no-show after the grace period; opens a replacement case | CastingAssociate |
| POST | `/central-casting/bookings/{id}/wrap-out` | Wrap out a checked-in booking; releases the holding seat | CastingAssociate |
| POST | `/central-casting/time-events` | Append a time event or correction to a booking's ledger | CastingAssociate |
| GET | `/central-casting/time-events` | List time events | All roles |
| GET | `/central-casting/time-events/{id}` | Get a time event | All roles |
| GET | `/central-casting/vouchers` | List vouchers | All roles |
| GET | `/central-casting/vouchers/{id}` | Get a voucher | All roles |
| GET | `/central-casting/vouchers/{id}/estimate` | Forward-looking gross estimate (any pre-PAID state) | All roles |
| POST | `/central-casting/vouchers/{id}/issue` | Issue a DRAFT voucher; computes and stores all pay fields | CastingAssociate |
| POST | `/central-casting/vouchers/{id}/dispute` | Dispute an ISSUED voucher (owner actor); ejects from an OPEN batch | BackgroundActor |
| POST | `/central-casting/vouchers/{id}/adjust` | Recompute and re-issue a voucher (OCC on voucher version) | CastingAssociate |
| POST | `/central-casting/bump-adjustments` | Claim a bump against a voucher | CastingAssociate |
| GET | `/central-casting/bump-adjustments` | List bump adjustments | All roles |
| GET | `/central-casting/bump-adjustments/{id}` | Get a bump adjustment | All roles |
| POST | `/central-casting/bump-adjustments/{id}/approve` | Approve a bump (decider must differ from requester) | CastingDirector |
| POST | `/central-casting/bump-adjustments/{id}/reject` | Reject a bump (decider must differ from requester) | CastingDirector |
| POST | `/central-casting/payroll-batches` | Create an OPEN payroll batch for a production | PayrollCoordinator |
| GET | `/central-casting/payroll-batches` | List payroll batches | All roles |
| GET | `/central-casting/payroll-batches/{id}` | Get a payroll batch | All roles |
| POST | `/central-casting/payroll-batches/{id}/items` | Add an ISSUED voucher to a batch (OCC on batch version) | PayrollCoordinator |
| POST | `/central-casting/payroll-batches/{id}/remove-item` | Remove a voucher from an OPEN batch | PayrollCoordinator |
| POST | `/central-casting/payroll-batches/{id}/submit` | Submit a batch; member vouchers move to SUBMITTED | PayrollCoordinator |
| POST | `/central-casting/payroll-batches/{id}/acknowledge` | Record the payroll company's response (acknowledger must differ from submitter) | PayrollCoordinator |
| GET | `/central-casting/replacement-cases` | List replacement cases | All roles |
| GET | `/central-casting/replacement-cases/{id}` | Get a replacement case | All roles |
| POST | `/central-casting/replacement-cases/{id}/offer-next` | Offer the top eligible standby; empty pool expires the case | CastingAssociate |
| POST | `/central-casting/replacement-cases/{id}/expire` | Manually expire an OPEN replacement case | CastingAssociate |
| POST | `/central-casting/standby-entries` | Register an actor on a call's standby pool | CastingAssociate |
| GET | `/central-casting/standby-entries` | List standby entries | All roles |
| GET | `/central-casting/standby-entries/{id}` | Get a standby entry | All roles |
| POST | `/central-casting/standby-entries/{id}/withdraw` | Withdraw an ACTIVE standby entry (owner actor or associate) | BackgroundActor, CastingAssociate |
| POST | `/central-casting/ratio-waivers` | Request a union slot reduction for a call | CastingDirector |
| GET | `/central-casting/ratio-waivers` | List ratio waivers | All roles |
| GET | `/central-casting/ratio-waivers/{id}` | Get a ratio waiver | All roles |
| POST | `/central-casting/ratio-waivers/{id}/approve` | Approve a waiver; lowers the call's required union slots | UnionRepresentative |
| POST | `/central-casting/ratio-waivers/{id}/deny` | Deny a waiver | UnionRepresentative |
| POST | `/_clock/set_current_utc` | Advance the logical clock; sweeps expired offers and cases | AgencyAdmin |

## 5. Error Code Catalogue

Trigger conditions for every error live in the narratives of §2 and §3; this table is the identifier-to-status index.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 Forbidden |
| `ERR_SOD_SELF_APPROVAL` | 403 Forbidden |
| `ERR_SOD_SELF_ACKNOWLEDGE` | 403 Forbidden |
| `ERR_PRODUCTION_NOT_FOUND` | 404 Not Found |
| `ERR_ACTOR_NOT_FOUND` | 404 Not Found |
| `ERR_CASTING_CALL_NOT_FOUND` | 404 Not Found |
| `ERR_LOOK_REQUIREMENT_NOT_FOUND` | 404 Not Found |
| `ERR_HOLDING_AREA_NOT_FOUND` | 404 Not Found |
| `ERR_BOOKING_NOT_FOUND` | 404 Not Found |
| `ERR_TIME_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_VOUCHER_NOT_FOUND` | 404 Not Found |
| `ERR_BUMP_ADJUSTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_PAYROLL_BATCH_NOT_FOUND` | 404 Not Found |
| `ERR_REPLACEMENT_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_STANDBY_ENTRY_NOT_FOUND` | 404 Not Found |
| `ERR_RATIO_WAIVER_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCTION_NOT_ACTIVE` | 409 Conflict |
| `ERR_PRODUCTION_NOT_WRAPPABLE` | 409 Conflict |
| `ERR_CALL_INVALID_STATE` | 409 Conflict |
| `ERR_CALL_NOT_ACCEPTING` | 409 Conflict |
| `ERR_BOOKING_INVALID_STATE` | 409 Conflict |
| `ERR_BOOKING_NOT_WRAPPED` | 409 Conflict |
| `ERR_VOUCHER_INVALID_STATE` | 409 Conflict |
| `ERR_BUMP_INVALID_STATE` | 409 Conflict |
| `ERR_BUMP_VOUCHER_LOCKED` | 409 Conflict |
| `ERR_BATCH_INVALID_STATE` | 409 Conflict |
| `ERR_CASE_INVALID_STATE` | 409 Conflict |
| `ERR_WAIVER_INVALID_STATE` | 409 Conflict |
| `ERR_STANDBY_NOT_ACTIVE` | 409 Conflict |
| `ERR_ACTOR_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_COMPLIANCE_INDEX_TOO_LOW` | 409 Conflict |
| `ERR_SHOOT_DATE_MISMATCH` | 409 Conflict |
| `ERR_NO_SHOW_TOO_EARLY` | 409 Conflict |
| `ERR_TURNAROUND_VIOLATION` | 409 Conflict |
| `ERR_DUPLICATE_BOOKING` | 409 Conflict |
| `ERR_NO_SLOT_AVAILABLE` | 409 Conflict |
| `ERR_NO_NONUNION_SLOT` | 409 Conflict |
| `ERR_HOLDING_AREA_FULL` | 409 Conflict |
| `ERR_TIME_EVENT_INVALID` | 409 Conflict |
| `ERR_VOUCHER_NOT_SUBMITTABLE` | 409 Conflict |
| `ERR_STALE_BATCH_VERSION` | 412 Precondition Failed |
| `ERR_STALE_VOUCHER_VERSION` | 412 Precondition Failed |
| `ERR_UNION_RATIO_SHORTFALL` | 422 Unprocessable Content |
| `ERR_WAIVER_REDUCTION_INVALID` | 422 Unprocessable Content |
| `ERR_BATCH_EMPTY` | 422 Unprocessable Content |

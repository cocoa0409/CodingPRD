# Car Show & Cruise-In Event Management API — Product Requirements Document

## 1. Introduction

A regional car club's annual show-and-shine is a deceptively intricate operation. Entrants register vehicles into judged or people's-choice classes under two pricing tiers, the gate crew must park several hundred cars across show fields without overruns, judges roam the rows with score sheets while spectators cast ballots, vendors and sponsors occupy booth rows, a stage runs under a municipal noise ordinance, and every plan sits one thunderstorm away from postponement or outright cancellation with its ensuing refund cascade. This document specifies the Car Show & Cruise-In Event Management API, the system of record that coordinates all of it for a single club-run show.

The API governs the full arc of the event. An `Organizer` configures the show, its classes, parking zones, judges, and sound program; `Participant` entrants register vehicles and pay; the `RegistrationDesk` countersigns waivers and checks arrivals onto the field; rostered `Judge` actors score their assigned classes; and `Vendor` applicants pay for and occupy booth spaces. Three design commitments run through every workflow. First, an event is steered by three independent postures — its lifecycle, its weather posture, and its sound-permit status — and those postures gate nearly every child operation. Second, all money moves through an append-only payment ledger posted against a per-event treasury, so every fee, goodwill credit, and refund is auditable. Third, award finalization and winner overrides are guarded by optimistic concurrency and a segregation-of-duties rule, because a trophy awarded from a stale or self-approved tabulation is a trophy handed back in the parking lot.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly five roles, spelled as follows: `Organizer`, `RegistrationDesk`, `Participant`, `Judge`, and `Vendor`. A request missing either header, or naming a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A recognized role attempting an operation outside its grant is rejected with `ERR_FORBIDDEN` (HTTP 403).

Two of the roles are operational identities not tied to any persisted entity. When `X-User-Role` is `Organizer`, `X-User-ID` is an opaque operator identifier: the server may record it — for example as `recorded_by_user_id` on a payment or as `finalized_by_user_id` on an event — but never compares it to any entity's `id`. The same holds when `X-User-Role` is `RegistrationDesk`: the identifier is opaque, recorded where an audit trail calls for it, and never used as an entity reference.

The remaining three roles are entity-backed, and ownership checks bind them to the resources they touch. When `X-User-Role` is `Participant`, `X-User-ID` is the `id` of the acting registrant; ownership checks on registrations, vehicles, waivers, and ballots compare the resource's registrant reference — such as `registrant_id` or `voter_registrant_id` — to `X-User-ID`. When `X-User-Role` is `Judge`, `X-User-ID` is the `id` of the acting judge, and score-sheet ownership compares the sheet's `judge_id` to it. When `X-User-Role` is `Vendor`, `X-User-ID` equals the `id` of the vendor's own booth application, so a vendor can read, pay, or cancel exactly one application: their own. An entity-backed actor touching a resource owned by someone else is rejected with `ERR_OWNERSHIP_VIOLATION` (HTTP 403).

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
- A request matching no route, or a route with an unsupported method, is answered in this same envelope with `ERR_NOT_FOUND` (HTTP 404).

### 2.3. Pagination

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. A `limit` below 1 or above 100, a negative `offset`, or a non-integer value for either parameter is rejected with `ERR_VALIDATION` rather than clamped.

Unless stated otherwise, every list endpoint returns its resources sorted by creation timestamp in ascending order.

The `meta` object of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`, so a client can always reconstruct where it sits in the full result set.

### 2.4. The Event's Three Governing Postures

An event is never described by a single status. Its `lifecycle_status` walks the operational arc `DRAFT` → `PUBLISHED` → `REGISTRATION_OPEN` → `REGISTRATION_LOCKED` → `JUDGING` → `TABULATING` → `FINALIZED` → `CLOSED`. Its `weather_posture` moves independently among `NORMAL`, `WATCH`, `POSTPONED`, and `CANCELLED`. Its `sound_permit_status` sits at `ACTIVE` or `SUSPENDED`. The three dimensions are independent: locking registration does not touch the weather posture, and suspending the sound permit does not advance the lifecycle.

Child operations across the system are gated by combinations of these postures. Entry-fee payment requires the event to be `REGISTRATION_OPEN` with weather `NORMAL` or `WATCH`; gate check-in accepts `REGISTRATION_OPEN` or `REGISTRATION_LOCKED` with weather anything but `CANCELLED`; scheduling a stage slot requires the permit to be `ACTIVE`. When a posture change renders dependent work impossible, the server reconciles the children itself: starting judging flips non-arrived entries to `NO_SHOW`, the third noise exceedance suspends the permit and cancels future sound slots, a cancellation decision runs a full refund cascade, and advancing the logical clock completes elapsed slots. Each such reconciliation mutates the affected resources, refreshing `updated_at` and incrementing `version` on every entity that carries those fields. The event's own `version` increments on every lifecycle, weather, or permit transition, and on every posted payment.

### 2.5. Common Resource Properties

Primary resources — events, classes, zones, registrants, vehicles, registrations, booth applications, judges, score sheets, ballots, awards, and sound slots — share a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp in the same format, refreshed upon any change to the resource.
- `version` (integer): a system-managed counter that starts at 1 when the resource is created, increments by one with every modification, and backs optimistic concurrency control where that applies.

Three record types are deliberately leaner because they are immutable once written. A `Payment` is an append-only ledger row, a `Waiver` is a signed legal certificate, and a `NoiseReading` is a sampled measurement; each carries only `id` and `created_at`, and both `updated_at` and `version` are absent from all three.

### 2.6. The Treasury Ledger and Monetary Precision

Every event owns a treasury, exposed as `treasury_cents`: the sum of `SUCCEEDED` payments whose `kind` is `ENTRY_FEE` or `BOOTH_FEE` for the event, minus the sum of its `SUCCEEDED` payments whose `kind` is `REFUND`. The treasury is recomputed immediately on every payment mutation, and every posted payment also increments the event's `version`.

Payments themselves are an append-only ledger. A payment's `status` is always `SUCCEEDED` at record time, there is no endpoint that updates or deletes a payment, and each row captures the recording actor in `recorded_by_user_id`. Exactly one of `registration_id` or `booth_application_id` is set on a payment — an entry fee names its registration, a booth fee its application, and a refund names whichever side of the ledger it draws down. The `amount_cents` value is positive for fees, and refunds are likewise recorded as positive magnitudes that are subtracted from the treasury. The `method` is one of `CASH`, `CARD`, or `CHECK`. Fee payments carry the `method` supplied by the caller; every `REFUND` payment — whether written by the postponement or cancellation cascades, an approved refund decision, or a booth cancellation — is recorded with method `CASH`.

Registration money is tracked on a gross basis: a registration's `paid_cents` accumulates its `SUCCEEDED` `ENTRY_FEE` payments and never decreases, while its `refunded_cents` accumulates that registration's `SUCCEEDED` `REFUND` payments; the net position is the difference of the two. Booth applications are tracked net instead: an application's `paid_cents` is the sum of its `SUCCEEDED` `BOOTH_FEE` payments minus its `REFUND` payments, so a refunded booth fee visibly drains back to zero.

All monetary values are integer cents. Where a calculation cannot land exactly on a cent, the final result is rounded half-up to whole cents in a single rounding step; the multi-step calculations in §3 state their own pinned rounding order where one exists.

### 2.7. The Logical Clock and Half-Open Time Windows

The platform runs on a logical clock rather than wall-clock time. At startup the clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time thereafter. An `Organizer`-only, test-driving capability advances the clock to a supplied `to_iso8601` instant and answers with the resulting `current_utc`. Advancing the clock past a scheduled sound slot's end marks the slot complete.

Everything time-sensitive in the domain reads this clock: the pre-registration pricing tier, the withdrawal refund windows, the judging and ballot windows, zone arrival windows, and the system-written timestamps `checked_in_at`, `withdrawn_at`, `submitted_at`, `signed_at`, and the default instant of a noise reading.

Every time window in the system is half-open — the start instant is inclusive and the end instant exclusive. The convention governs the judging window, the ballot window, zone arrival windows, sound-slot scheduling, and the nightly noise curfew. Because the curfew is configured as wall-clock `HH:MM` strings, a curfew window may legitimately wrap midnight, as a 22:00–07:00 window does.

### 2.8. Optimistic Concurrency Control

Exactly two write operations carry optimistic concurrency protection; no other endpoint accepts a version field.

Finalizing tabulation requires the request to carry `expected_event_version`, holding the event `version` the caller last observed. If the event's version has advanced since that read — a weather decision, a treasury-moving payment, or an earlier finalization all advance it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Finalization is naturally repeatable: re-finalization exists precisely to recompute awards that were reverted after a winner withdrew, so a sequential second call would otherwise legitimately succeed. The version check is what makes a stale view fail instead of silently recomputing on top of an event the caller has not observed.

Overriding an award winner requires `expected_award_version`, holding the award's last observed `version`. An override legitimately supersedes the stored winner, so a stale view must fail rather than silently re-supersede a winner set by a more recent override or recompute; a mismatch against the award's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.9. Nested Resource Retrieval and the Validation Priority Order

For URLs that nest identifiers — an event's classes, a registrant's vehicles — the server validates identifiers strictly left to right: the first path identifier that does not resolve to an existing resource fails the request with `ERR_NOT_FOUND` (HTTP 404), and only after the path resolves are body-supplied foreign-key targets checked, again left to right.

Beyond existence, every request walks a fixed validation cascade, and a failure at an earlier level masks all later checks. The levels, in order:

1. Authentication — both headers present and the role recognized, else `ERR_UNAUTHENTICATED`.
2. Authorization — the role appears in the endpoint's grant list, else `ERR_FORBIDDEN`.
3. Ownership — entity-backed actors confined to their own resources, else `ERR_OWNERSHIP_VIOLATION`.
4. Request shape — required fields present, enum values in range, numbers in range, a score sheet's `criteria_scores` holding exactly the five known criteria with integer points from 0 to 10, and class codes unique within the event: violations carry `ERR_VALIDATION`, except a duplicated class code, which carries `ERR_DUPLICATE_CLASS_CODE`.
5. Existence — path identifiers, then body foreign-key targets, left to right, else `ERR_NOT_FOUND`.
6. State preconditions — the transition's state gates, including the optimistic-concurrency match that yields `ERR_STALE_VERSION`. Within this layer the target entity's own state is checked before any cross-entity state: a score sheet that is already `LOCKED` yields `ERR_INVALID_SCORE_SHEET_STATE` even when the event has also left `JUDGING`.
7. Business safety — a signed waiver and, for minors, a guardian signature before check-in (`ERR_WAIVER_NOT_SIGNED`, `ERR_GUARDIAN_SIGNATURE_REQUIRED`), a non-empty liability policy before publish (`ERR_INSURANCE_POLICY_MISSING`), and an active sound permit before scheduling a slot (`ERR_SOUND_PERMIT_SUSPENDED`).
8. Business temporal — window membership: the judging window for sheet creation and submission (`ERR_JUDGING_WINDOW_CLOSED`), the ballot window (`ERR_BALLOT_WINDOW_CLOSED`), and zone arrival windows at check-in (`ERR_OUTSIDE_ARRIVAL_WINDOW`).
9. Business constraints — capacity, eligibility, uniqueness, and overlap: `ERR_CLASS_FULL`, `ERR_ZONE_FULL`, `ERR_ZONE_TYPE_INELIGIBLE`, `ERR_VEHICLE_CLASS_INELIGIBLE`, `ERR_DUPLICATE_REGISTRATION`, `ERR_DUPLICATE_BALLOT`, `ERR_DUPLICATE_SCORE_SHEET`, `ERR_JUDGE_NOT_ASSIGNED`, `ERR_JUDGE_CONFLICT_OF_INTEREST`, `ERR_VOTE_INELIGIBLE_CLASS`, `ERR_SOUND_SLOT_OVERLAP`, `ERR_BOOTH_SPACE_CONFLICT`, `ERR_BOOTH_SPACES_NOT_CONTIGUOUS`, `ERR_POWER_NOT_AVAILABLE`, and `ERR_SEGREGATION_OF_DUTIES`.
10. Fiscal rules — a payment's amount must equal the assessed fee (`ERR_PAYMENT_AMOUNT_MISMATCH`), and an approved refund must not exceed the net amount paid (`ERR_REFUND_EXCEEDS_PAID`).

Because state preconditions sit at level 6, above safety at level 7, a stale registration state surfaces before a missing waiver is even considered — at the gate, `ERR_INVALID_REGISTRATION_STATE` beats `ERR_WAIVER_NOT_SIGNED`. And because temporal checks at level 8 sit above constraints at level 9, a sheet submitted outside the judging window reports `ERR_JUDGING_WINDOW_CLOSED` rather than an assignment error.

## 3. Business Logic & Workflows

### 3.1. Setting Up the Show: Events, Classes, Zones, and the Publishing Gate

An `Organizer` opens a new show by supplying its `name`, the `event_date` as a calendar date in `YYYY-MM-DD` form, and the five instants that discipline the day: `gates_open_at`, `judging_start_at`, `judging_end_at`, `ballot_close_at`, and `prereg_deadline`. The noise curfew arrives as two wall-clock strings, `curfew_start` and `curfew_end`. The organizer may also record the club's `liability_policy_number`, which defaults to an empty string, and choose a `tabulation_method` of `STRAIGHT_AVERAGE` or `DROP_EXTREMES`, defaulting to `STRAIGHT_AVERAGE` when omitted. A new event begins in `DRAFT` with `weather_posture` at `NORMAL`, `sound_permit_status` at `ACTIVE`, `treasury_cents` at zero, `noise_exceedance_count` at zero, and `finalized_by_user_id` empty. Configuration may be revised freely while the event remains in `DRAFT`, with each accepted update incrementing the event's `version`; once the show has been published its configuration is frozen, and an update attempted in any later lifecycle state is rejected with `ERR_INVALID_EVENT_STATE`.

While the event is in `DRAFT` or `PUBLISHED`, the organizer defines the show's classes; attempting to create a class in any later lifecycle state is rejected with `ERR_INVALID_EVENT_STATE`. Each class carries a `code` that is unique within the event — reusing one is rejected with `ERR_DUPLICATE_CLASS_CODE` — plus a display `name`, an eligible model-year band from `min_year` through `max_year` with both ends inclusive (a `min_year` greater than `max_year` is malformed and rejected with `ERR_VALIDATION`), the two price points `prereg_fee_cents` and `day_of_fee_cents` (each zero or greater), a `capacity` of at least one, a `judging_mode` of `JUDGED`, `PEOPLES_CHOICE`, or `BOTH`, and an `award_depth` between 1 and 3 that determines how many class-place trophies the class produces. A class's `confirmed_count` is a live computed tally of its registrations sitting in `PENDING_PAYMENT`, `CONFIRMED`, or `CHECKED_IN`.

Zones are defined in the same `DRAFT`-or-`PUBLISHED` window, and zone creation in any later state is likewise rejected with `ERR_INVALID_EVENT_STATE`. A zone has a `name`, a `zone_type` of `SHOW_FIELD`, `OVERFLOW`, or `VENDOR_ROW`, a `capacity` of at least one (vehicle spots on the field zones, booth spaces on a vendor row), a `has_power` flag defaulting to false, and an optional arrival window given by `arrival_window_start` and `arrival_window_end`; when both are absent — their default — the zone declares no arrival window at all, and when present the window is half-open. The window is enforced at check-in only when both bounds are present; a zone carrying just one of the two declares no enforced window. A zone's `assigned_count` is computed: on `SHOW_FIELD` and `OVERFLOW` zones it is the number of registrations parked there with status `CHECKED_IN`, while on a `VENDOR_ROW` it is the number of booth spaces currently occupied.

Publishing is the show's first real gate, moving the event `DRAFT` → `PUBLISHED`, and it enforces four preconditions: the event is in `DRAFT`; `liability_policy_number` is non-empty, else `ERR_INSURANCE_POLICY_MISSING`; at least one class and at least one zone exist, else `ERR_VALIDATION`; and the day's timeline is coherent — `prereg_deadline` strictly before `gates_open_at`, `gates_open_at` at or before `judging_start_at`, and `judging_start_at` strictly before `judging_end_at` — else `ERR_VALIDATION`. From `PUBLISHED`, opening registration requires the weather posture to be `NORMAL` or `WATCH` and advances the event to `REGISTRATION_OPEN`; locking registration later moves `REGISTRATION_OPEN` → `REGISTRATION_LOCKED` with no further gate. Each of these transitions increments the event's `version`.

Judges may be rostered at any point before the event is `CLOSED` — rostering one once the event is `CLOSED` is rejected with `ERR_INVALID_EVENT_STATE`: each judge carries a `name`, an `email` (which doubles as the conflict-of-interest detector described in §3.5), and `assigned_class_ids`, the list of classes the judge may score — an empty list simply means no assignments yet, and each listed id must resolve to a class of the same event, else `ERR_NOT_FOUND`. A judge's `submitted_sheet_count` is the computed count of that judge's sheets sitting in `SUBMITTED` or `LOCKED`. For day-of oversight, the organizer and the desk share a computed summary read of the event's aggregates: `treasury_cents`, `refunded_cents_total`, `registration_count`, `checked_in_count`, `noise_exceedance_count`, `sound_permit_status`, `lifecycle_status`, and `weather_posture`. Here `registration_count` counts every registration of the event regardless of status, `checked_in_count` counts those currently `CHECKED_IN`, and `refunded_cents_total` is the sum of the event's `SUCCEEDED` `REFUND` payments. Event lists may be filtered by `lifecycle_status`, and class, zone, and judge lists paginate per §2.3.

### 3.2. Registration and Entry-Fee Pricing

Before any vehicle can be entered, its owner needs a participant profile holding `full_name`, an `email` (uniqueness is not enforced), and two flags that default to false: `club_member`, which drives both the member fee discount and the doubled ballot weight, and `is_minor`, which changes what the liability waiver requires. A `Participant` creates and reads only their own profile; the desk and the organizer may create profiles on behalf of walk-ins. Vehicles are added under a registrant with a `year`, `make`, and `model`, and a participant manages only their own garage.

A registration is created from a payload naming the `event_id`, `registrant_id`, `vehicle_id`, and `class_id`; a `Participant` may register only under their own `registrant_id`. The named vehicle must belong to the named registrant and the named class to the named event, else `ERR_NOT_FOUND`. Creation is not gated on the event's lifecycle or weather posture. Three eligibility guards fire at creation, after the shape and existence checks of §2.9. The vehicle's `year` must fall inside the class's `min_year`-to-`max_year` band, else `ERR_VEHICLE_CLASS_INELIGIBLE`. The same vehicle may hold only one non-terminal registration per event — a second create while the first is still alive in `PENDING_PAYMENT`, `CONFIRMED`, or `CHECKED_IN` is rejected with `ERR_DUPLICATE_REGISTRATION`. And the class must still have room: once its `confirmed_count` has reached `capacity`, further creates are rejected with `ERR_CLASS_FULL`, while a create arriving below capacity succeeds — so the final seat is filled exactly at capacity.

Pricing is decided entirely by the logical clock, and any client-supplied tier is ignored. When the clock reads earlier than the event's `prereg_deadline`, the registration prices at the `PREREG` tier; at or after the deadline it prices at `DAY_OF`, and the resulting `pricing_tier` and `fee_cents` are frozen on the row at creation. The `DAY_OF` tier is flat: `fee_cents` is simply the class's `day_of_fee_cents`, with no member or multi-vehicle discount, so identical inputs price higher at the gate than they would have in advance. The `PREREG` tier starts from the class's `prereg_fee_cents` and applies up to two discounts: a club member pays ten percent less, and the fee drops a further twenty-five percent when this is the registrant's second or later vehicle for the same event — that is, when at least one other registration of theirs for the event, in `PENDING_PAYMENT`, `CONFIRMED`, or `CHECKED_IN`, was created before this one. The discounted product is rounded half-up to whole cents in a single rounding at the final multiplication.

A fresh registration sits in `PENDING_PAYMENT`, and the class's `confirmed_count` rises by one. Settling it is an exact-amount affair: the participant (for their own registration) or the desk records a payment whose `amount_cents` equals the frozen `fee_cents` — anything else is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH` — alongside a `method`. The registration must still be in `PENDING_PAYMENT`, else `ERR_INVALID_REGISTRATION_STATE`, and the event must be in `REGISTRATION_OPEN` with weather `NORMAL` or `WATCH`, else `ERR_INVALID_EVENT_STATE`. An accepted payment writes a `Payment` of kind `ENTRY_FEE`, grows the registration's `paid_cents`, credits the event treasury (incrementing the event's `version`), and moves the registration to `CONFIRMED` with its own `version` incremented. Registrations may be listed filtered by `event_id`, `registrant_id`, `vehicle_id`, `class_id`, `assigned_zone_id`, or `status`, and each registration's payment ledger is listable on its own. A `Participant` listing registrations sees only their own.

### 3.3. Waivers and Gate Check-In

No car rolls onto the field without a signed liability waiver. A waiver is signed for a specific registrant at a specific event from a payload of `event_id`, `registrant_id`, and the typed legal signature `signature_name`; when the registrant's `is_minor` flag is set, `guardian_name` is required and its absence is rejected with `ERR_GUARDIAN_SIGNATURE_REQUIRED`. The server stamps `signed_at` from the logical clock, the waiver is immutable once created, and exactly one waiver exists per registrant per event — a second signing for the same registrant and event is rejected with `ERR_VALIDATION`. Waivers may be listed filtered by `event_id` or `registrant_id` for desk audits; a `Participant` listing waivers sees only their own.

Check-in itself is a `RegistrationDesk` operation whose payload names the target `zone_id`. Its preconditions evaluate in the cascade order of §2.9, with the registration's own state first: the registration must be `CONFIRMED`, else `ERR_INVALID_REGISTRATION_STATE` — and this state check is reported before any safety check is even considered. Cross-entity state follows: the event must be in `REGISTRATION_OPEN` or `REGISTRATION_LOCKED` with `weather_posture` anything but `CANCELLED`, else `ERR_INVALID_EVENT_STATE`. Safety comes next: a waiver must exist for the registrant and event, else `ERR_WAIVER_NOT_SIGNED`, and a minor's waiver without `guardian_name` fails as `ERR_GUARDIAN_SIGNATURE_REQUIRED`. The `zone_id` target is resolved next — an unknown zone, or one belonging to a different event, fails with `ERR_NOT_FOUND`. Then the temporal gate: when the chosen zone declares an arrival window, the logical clock must sit inside the half-open interval from `arrival_window_start` to `arrival_window_end`, else `ERR_OUTSIDE_ARRIVAL_WINDOW`. Finally the constraint checks: the zone's `zone_type` must be `SHOW_FIELD` or `OVERFLOW` — driving a show car into a `VENDOR_ROW` is rejected with `ERR_ZONE_TYPE_INELIGIBLE` — and the zone must still have room, `assigned_count` below `capacity`, else `ERR_ZONE_FULL`.

A successful check-in parks the car deterministically: `assigned_zone_id` is set to the chosen zone, `spot_number` receives the lowest free spot integer in that zone — spots are numbered from 1 up to `capacity` — `checked_in_at` records the clock, the zone's `assigned_count` rises by one, and the registration's `version` increments. When a checked-in car later pulls out, its freed spot returns to the pool and can be handed out again as the lowest free spot.

### 3.4. Withdrawals and Refunds

Life happens, and entrants withdraw. A withdrawal may be filed by the owning `Participant` or by the desk, with an optional `reason`, and what it does depends on both the registration's state and the refund tier measured at the moment of withdrawal.

The tier is measured in hours — fractional hours allowed — from the withdrawal instant to the event's `gates_open_at`. Withdrawing at least 168 hours before gates open, a full week out, earns a 100% refund tier; at least 48 hours before gates open earns 50%; anything closer earns nothing. The boundaries are inclusive: exactly 168.0 hours out is a full refund, and exactly 48.0 hours out is a half refund.

From `PENDING_PAYMENT`, withdrawal is simple: the registration moves straight to `WITHDRAWN`, `withdrawn_at` is stamped from the clock, and the class's `confirmed_count` is decremented; nothing was ever paid, so nothing is refundable.

From `CONFIRMED`, the tier decides the path, provided the weather posture is not `CANCELLED` — a withdrawal attempted while `CANCELLED` is rejected with `ERR_INVALID_EVENT_STATE`. A positive tier parks the registration in `REFUND_REQUESTED` with `withdrawn_at` stamped, awaiting an organizer's decision. A zero tier — withdrawal inside 48 hours of gates open — terminates immediately in `WITHDRAWN`: `withdrawn_at` is stamped, every ballot cast for the entry flips `VALID` → `VOID`, and the class's `confirmed_count` is decremented.

The refund decision belongs to the `Organizer` and carries a `decision` of `APPROVE` or `DENY` plus an optional `note`. On `APPROVE`, the refund amount is an explicit `amount_cents` when the organizer supplies one — the mechanism for partial goodwill gestures — and otherwise the policy amount: the registration's net paid, meaning `paid_cents` minus `refunded_cents` measured at decision time, multiplied by the tier percentage that was frozen at `withdrawn_at`, rounded half-up to whole cents. Either way the amount must not exceed the net paid, else `ERR_REFUND_EXCEEDS_PAID`. The decision carries no lifecycle or weather gate of its own — only the registration's `REFUND_REQUESTED` state gates it — and an approved amount of zero or less writes no `REFUND` row while still landing the registration in `REFUNDED`. Approval writes a `REFUND` payment, grows `refunded_cents`, debits the event treasury (incrementing the event's `version`), voids the entry's ballots, decrements the class's `confirmed_count`, and lands the registration in `REFUNDED`. On `DENY`, the registration returns to `CONFIRMED` and `withdrawn_at` is cleared back to null.

A day-of pull-out from `CHECKED_IN` is never refundable and moves straight to `WITHDRAWN`: the spot is freed for reuse and the zone's `assigned_count` drops by one, though `assigned_zone_id` is retained on the registration for audit; the entry's ballots flip `VALID` → `VOID`; and any award in `COMPUTED` or `FINALIZED` that this entry had won reverts to `PENDING` with its winner fields cleared — awards already `PRESENTED` are left standing. Withdrawal from `REFUND_REQUESTED` or from a terminal state is rejected with `ERR_INVALID_REGISTRATION_STATE`, and no lifecycle gate applies to withdrawal beyond the weather gate on `CONFIRMED`.

Two system-driven endings complete the picture. When judging begins, every registration still sitting in `CONFIRMED` — the gate no-shows — flips to `NO_SHOW` and the class count drops accordingly. And when the event closes, every registration still `CHECKED_IN` completes to `COMPLETED`. A registration's terminal states are `WITHDRAWN`, `REFUNDED`, `NO_SHOW`, and `COMPLETED`. Weather cancellations route through their own cascade in §3.7, which auto-approves refund requests rather than waiting for individual decisions.

### 3.5. Judging and Score Sheets

Starting judging moves the event `REGISTRATION_LOCKED` → `JUDGING` and is refused outright when the weather posture is `CANCELLED`. The transition does three things at once. First, every registration still in `CONFIRMED` flips to `NO_SHOW`, decrementing its class count — the field is now frozen to the cars actually parked on it. Second, the award structure materializes in `PENDING`: for each class whose `judging_mode` is `JUDGED` or `BOTH`, `award_depth` rows with `award_kind` `CLASS_PLACE` are created with `place` running from 1 to `award_depth`; for each class whose mode is `PEOPLES_CHOICE` or `BOTH`, a single row with `award_kind` `PEOPLES_CHOICE` and a null `place` is created; and exactly one `BEST_OF_SHOW` row is created with its `class_id` and `place` left null, since best-of-show floats above the classes. Every materialized row starts with null winner fields, an empty-string `tie_break_log`, and `overridden` false. Third — because a class with nothing to judge should not stall the show — if at least one judged class exists and every judged class is already complete, meaning no `CHECKED_IN` registration in any judged class lacks a `SUBMITTED` or `LOCKED` sheet from any judge assigned to that class, the event auto-advances `JUDGING` → `TABULATING` immediately. Any such auto-advance locks every `SUBMITTED` sheet of the event into `LOCKED`, exactly as the submission-triggered advance described below does. Every hop increments the event's `version`.

A `Judge` scores a car by creating a score sheet from a payload of `registration_id` and `criteria_scores`; the sheet's `judge_id` is taken from the judge's own `X-User-ID`, never from the payload; an `X-User-ID` that resolves to no judge rostered on the entry's event fails with `ERR_NOT_FOUND`. The `criteria_scores` list holds exactly five items, each pairing a `criterion` — one of `EXTERIOR`, `INTERIOR`, `ENGINE`, `AUTHENTICITY`, or `CONDITION` — with integer `points` from 0 to 10; a malformed list is rejected with `ERR_VALIDATION`. The target registration must be a `CHECKED_IN` entry — any other status is rejected with `ERR_INVALID_REGISTRATION_STATE` — in an event sitting in `JUDGING`, else `ERR_INVALID_EVENT_STATE`, and in one of the judge's assigned classes: an entry in a class outside the judge's `assigned_class_ids` is rejected with `ERR_JUDGE_NOT_ASSIGNED`. A judge may hold only one sheet per registration — a second is rejected with `ERR_DUPLICATE_SCORE_SHEET` — and may never score a class they compete in: when the judge's `email` matches a registrant holding a non-terminal registration in that same class, creation is rejected with `ERR_JUDGE_CONFLICT_OF_INTEREST`. Creation is a temporal operation too, accepted only inside the judging window from `judging_start_at` (inclusive) to `judging_end_at` (exclusive), else `ERR_JUDGING_WINDOW_CLOSED`. Each new sheet starts in `DRAFT`, and its `sheet_total` is computed at once: the five criterion points are weighted — `EXTERIOR` at 1.0, `INTERIOR` at 0.75, `ENGINE` at 1.5, `AUTHENTICITY` at 2.0, and `CONDITION` at 1.25 — summed, and rounded half-up to one decimal place.

Submitting a sheet is the judge's own act on their own sheet, and its guards again follow the cascade. The sheet must be in `DRAFT` — a `SUBMITTED` or `LOCKED` sheet yields `ERR_INVALID_SCORE_SHEET_STATE`, and per §2.9 this own-state check is reported before the event's state is examined. The event must be in `JUDGING`, else `ERR_INVALID_EVENT_STATE`. The clock must sit inside the judging window, else `ERR_JUDGING_WINDOW_CLOSED`, and this temporal check takes priority over the final constraint, that the judge is still assigned to the sheet's class, else `ERR_JUDGE_NOT_ASSIGNED`. On acceptance, `submitted_at` is stamped from the clock on the first submission, the judge's `submitted_sheet_count` rises by one, and the sheet moves `DRAFT` → `SUBMITTED`. Then the class-completion bubble-up runs: the system recomputes completion across the judged classes, and if this submission was the last outstanding registration-by-judge pair of the last incomplete judged class, the event auto-transitions `JUDGING` → `TABULATING`, and every `SUBMITTED` score sheet for the event locks into `LOCKED`, its terminal state.

An `Organizer` may send a `SUBMITTED` sheet back to `DRAFT` — with an optional `reason` — but only while the event remains in `JUDGING`; once tabulation has begun, reopening is rejected with `ERR_INVALID_EVENT_STATE`. Reopening decrements the judge's `submitted_sheet_count` by one, and a later resubmission raises it again by one, so the count always equals the judge's sheets currently in `SUBMITTED` or `LOCKED`. Sheets may be listed filtered by `judge_id`, `registration_id`, or `status`; a `Judge` listing sheets sees only their own.

### 3.6. People's Choice, Tabulation, and Awards

Spectator sentiment enters the system as ballots. A `Participant` casts one from a payload of `event_id` and the favoured entry's `registration_id`; the ballot's `voter_registrant_id` is taken from the caller's `X-User-ID` — a caller whose `X-User-ID` resolves to no registrant fails with `ERR_NOT_FOUND` — and one voter gets exactly one ballot per event — a second attempt is rejected with `ERR_DUPLICATE_BALLOT`. Ballots are accepted only while the event is in `JUDGING` and the logical clock sits inside the ballot window, the half-open interval from `gates_open_at` to `ballot_close_at`; a ballot cast outside that window or while the event is not in `JUDGING` is rejected with `ERR_BALLOT_WINDOW_CLOSED`. The target entry's class must actually be a people's-choice class — `judging_mode` `PEOPLES_CHOICE` or `BOTH` — and a ballot aimed at a `JUDGED`-only class is rejected with `ERR_VOTE_INELIGIBLE_CLASS`. The ballot's `weight` is computed from the voter: 2 for a `club_member`, 1 otherwise. A ballot is born `VALID` and flips to `VOID` the moment its voted registration becomes `WITHDRAWN` or `REFUNDED`. The ballot box may be listed filtered by `event_id`, `registration_id`, `voter_registrant_id`, or `status`.

Tabulation finalization is the operation that turns scoring into trophies, and it is available from `TABULATING` or `FINALIZED` — and, exceptionally, directly from `JUDGING` for people's-choice-only events, which have no judged class and therefore never auto-advance out of `JUDGING`. The request must carry `expected_event_version` per the OCC rule of §2.8, and a mismatch is rejected with `ERR_STALE_VERSION`. Finalization recomputes every award in `PENDING` or `COMPUTED` that has not been manually overridden, and each recomputed award walks `PENDING` → `COMPUTED` → `FINALIZED` within the same request. The caller's `X-User-ID` is recorded as the event's `finalized_by_user_id`, the event's `lifecycle_status` moves to `FINALIZED`, and the event's `version` increments. Because finalization is repeatable, it doubles as the recovery path after a winner's withdrawal reverted an award to `PENDING`.

Judged scoring feeds each `CLASS_PLACE` award. A registration's class score draws only on its `LOCKED` sheets, and only `CHECKED_IN` entries rank. When the event's `tabulation_method` is `STRAIGHT_AVERAGE`, or the entry has fewer than three locked sheets, the class score is the average of its sheet totals, rounded half-up to two decimal places. Under `DROP_EXTREMES` with three or more locked sheets, exactly one highest and one lowest sheet total are discarded before averaging, and the result is likewise rounded half-up to two decimals. The rounding order is pinned: each sheet's total is rounded to one decimal first, then the average is taken, then the average is rounded to two decimals — averaging unrounded weighted sums and rounding once at the end is a different, forbidden order that produces different scores.

Places within a judged class are assigned by a five-level ranking chain over the class's `CHECKED_IN` entries holding at least one `LOCKED` sheet: higher class score first; then higher condition average, the entry's `CONDITION` points averaged across its locked sheets and rounded half-up to two decimals; then more locked sheets; then the earlier `checked_in_at`, favouring the car that arrived first; and finally the newer vehicle `year`. Places run from 1 to the class's `award_depth`, and when the class has fewer scored entries than places, the unfilled places keep a null `winner_registration_id` with `tie_break_log` recording `INSUFFICIENT_ENTRIES`. For a decided award, `winner_score` holds the winning class score and `tie_break_log` records which level of the chain made the decision. The recorded value names the deciding level — `CLASS_SCORE`, `CONDITION_AVG`, `SHEET_COUNT`, `CHECKED_IN_AT`, or `VEHICLE_YEAR` — judged by comparison against the next-ranked entry, and the last-ranked (or only) entry records `CLASS_SCORE`.

The people's-choice tally works per class over `VALID` ballots whose voted registration is still `CHECKED_IN` at finalize time: an entry's tally is the sum of its ballots' `weight`. Ranking is by higher tally, then by the higher count of member ballots — those with `weight` 2 — then by the earlier `checked_in_at`, then by the newer vehicle `year`; here `winner_score` holds the winning tally, and the `tie_break_log` likewise names the deciding level — `TALLY`, `MEMBER_BALLOTS`, `CHECKED_IN_AT`, or `VEHICLE_YEAR` — with a sole candidate recording `TALLY`. A class with zero valid ballots across all its entries keeps a null winner with `tie_break_log` recording `NO_VALID_BALLOTS`. The single `BEST_OF_SHOW` award goes to the highest-scoring `CLASS_PLACE` place-1 winner across the judged classes, with ties resolved by the same tie-break chain; its candidates are the place-1 winners named by the `CLASS_PLACE` awards recomputed in the same finalization pass, and when there are none the award keeps a null winner with `tie_break_log` recording `INSUFFICIENT_ENTRIES`, while a decided `BEST_OF_SHOW` always records `CLASS_SCORE` in its log.

Two human overrides complete the awards story. An `Organizer` may override the winner of an award in `COMPUTED` or `FINALIZED` — attempting it on a `PENDING` or `PRESENTED` award is rejected with `ERR_INVALID_AWARD_STATE` — by supplying the new `winner_registration_id`, the OCC token `expected_award_version` per §2.8, and an optional `reason`. Segregation of duties applies: the caller must differ from the event's `finalized_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`, so the organizer who finalized the tabulation cannot also hand-pick winners. The named winner must reference a `CHECKED_IN` registration in the award's class — for `BEST_OF_SHOW`, any judged class — else `ERR_VALIDATION`. A successful override sets the winner, clears `winner_score` to null, marks the award `overridden`, writes `MANUAL_OVERRIDE` into `tie_break_log`, and lands the award in `FINALIZED`; overridden awards are never recomputed by later finalizations. Conversely, when an award's winner becomes `WITHDRAWN` or `REFUNDED`, a non-overridden award in `COMPUTED` or `FINALIZED` reverts to `PENDING` with `winner_registration_id`, `winner_score`, and `tie_break_log` cleared (the winner fields to null, the log to an empty string); a `PRESENTED` award is never reverted. Presentation itself moves an award `FINALIZED` → `PRESENTED`, its terminal state, and presenting anything not yet `FINALIZED` is rejected with `ERR_INVALID_AWARD_STATE`. Awards are readable by all five roles, filtered by `event_id`, `class_id`, `winner_registration_id`, or `status`.

### 3.7. Weather Posture and the Refund Cascade

Weather management is an `Organizer` duty exercised through a single decision endpoint carrying a `posture` and an optional `reason`. The allowed posture moves are: `NORMAL` → `WATCH` to raise caution; `WATCH` → `NORMAL` to stand back down; `NORMAL` or `WATCH` → `POSTPONED` when the show is delayed; `POSTPONED` → `NORMAL` on the all-clear; and `NORMAL`, `WATCH`, or `POSTPONED` → `CANCELLED` when the day is lost. A decision that does not correspond to an allowed move from the current posture — a second `WATCH`, or any move once `CANCELLED` — is rejected with `ERR_INVALID_EVENT_STATE`. Every accepted weather transition increments the event's `version`.

Declaring `POSTPONED` issues a goodwill credit without disturbing anyone's entry: for every registration in `CONFIRMED` or `CHECKED_IN`, the system writes a `REFUND` payment equal to 25% of that registration's gross `paid_cents`, rounded half-up to whole cents, adds it to the registration's `refunded_cents`, and debits the event treasury. A registration whose credit rounds to zero has no payment row written for it. The registrations themselves stay exactly where they were — the show will go on, just later.

Declaring `CANCELLED` fires the full four-level cascade. Level one: every registration in `CONFIRMED` or `CHECKED_IN` moves to `REFUND_REQUESTED`, with `withdrawn_at` stamped from the clock where not already set. Registrations already sitting in `REFUND_REQUESTED` are not swept into the cascade; they remain decidable through the normal refund-decision path. Level two: for each such registration the system auto-creates a `REFUND` payment under the cancellation policy — 100% of gross `paid_cents` — evaluated with a pinned two-pass order that resolves the circular dependency between individual refunds and the treasury they draw from. Pass one computes every registration's policy refund against a treasury snapshot taken before any of the batch's refunds post, with registrations processed in creation order, earliest first. Pass two applies the cap: if the policy refunds total more than the snapshot, each registration's base refund becomes its policy refund scaled by the snapshot-to-total ratio and rounded down to whole cents, and the cents left over by that truncation are distributed one cent at a time to registrations in creation order until the snapshot is exactly exhausted; if the snapshot covers the batch, every registration is refunded its full policy amount. Level three: each `SUCCEEDED` refund debits `treasury_cents`, accrues into the registration's `refunded_cents`, and moves that registration `REFUND_REQUESTED` → `REFUNDED`; a registration whose capped amount computes to zero posts no payment row yet still lands in `REFUNDED`. Level four: each registration that lands in `REFUNDED` voids its ballots (`VALID` → `VOID`), reverts any award in `COMPUTED` or `FINALIZED` it had won back to `PENDING` with the `tie_break_log` cleared, and — where the car had been `CHECKED_IN` — releases its spot and decrements the zone's `assigned_count`.

One more duty hides inside the weather decision: the organizer all-clear. A decision setting `posture` to `NORMAL` — which the state rules allow from `WATCH` or `POSTPONED` — also reinstates a `SUSPENDED` sound permit to `ACTIVE`, and this is the only route by which the permit is reinstated.

Closing the books moves the event `FINALIZED` → `CLOSED`, and is additionally permitted from any lifecycle state once the weather posture is `CANCELLED`, so a rained-out show can still be formally shut; any other attempt to close is rejected with `ERR_INVALID_EVENT_STATE`. On close, every registration still `CHECKED_IN` completes to `COMPLETED`, and the event's `version` increments.

### 3.8. The Sound Program and Noise Compliance

The stage program is planned as sound slots, each created by an `Organizer` with a `performer_name` for the band, DJ, or announcement block, a half-open `slot_start`-to-`slot_end` window in which the start must precede the end, and an informational `expected_db` declaration. Two guards apply at scheduling time: the event's sound permit must be `ACTIVE`, else `ERR_SOUND_PERMIT_SUSPENDED`, and the requested window must not intersect any existing `SCHEDULED` slot under the half-open convention — back-to-back adjacency, one slot starting exactly as another ends, is allowed — else `ERR_SOUND_SLOT_OVERLAP`. A slot lives in `SCHEDULED` until it is explicitly cancelled by the organizer (moving it to `CANCELLED`; cancelling a slot that is not `SCHEDULED` is rejected with `ERR_INVALID_EVENT_STATE`), is cancelled automatically when the permit suspends and the slot's `slot_start` is still strictly in the future, or completes to `COMPLETED` when the logical clock advances to or past its `slot_end` — a sweep evaluated at the moment the clock is set. Slots may be listed filtered by `status`.

Noise compliance is measured one reading at a time, recorded by the `Organizer` or the `RegistrationDesk` with a `reading_db` value (any positive number), a `source` of `STAGE`, `PA_SYSTEM`, `EXHAUST`, or `CROWD`, and an optional `recorded_at` that defaults to the logical clock's current instant. Each reading is evaluated against the event's curfew. The reading's clock time, taken as `HH:MM` in UTC — this is a single-timezone deployment, so UTC stands in for venue-local time — is curfew-time when it falls inside the half-open window from `curfew_start` to `curfew_end`; when the window wraps midnight (the start later than the end), curfew-time means at or after `curfew_start`, or before `curfew_end`. The applicable `limit_db` is 85.0 during curfew hours and 95.0 outside them, and `is_curfew` records which regime applied. An `is_exceedance` is flagged only when the reading is strictly greater than the applicable limit — a reading exactly at the limit is compliant.

Each exceedance increments the event's `noise_exceedance_count`, and the count is a tripwire: whenever a newly recorded exceedance finds the permit `ACTIVE` and the count at 3 or higher, `sound_permit_status` flips `ACTIVE` → `SUSPENDED`, every `SCHEDULED` sound slot whose start is still in the future is `CANCELLED` (slots already underway are not), and the event's `version` increments. While the permit is suspended, new sound slots are refused as described above; the permit returns to `ACTIVE` only through the weather all-clear of §3.7. Readings may be listed filtered by `is_exceedance` for ordinance reporting.

### 3.9. Vendor and Sponsor Booth Allocation

Booth inventory is sold through applications, created by an `Organizer` on a vendor's behalf with the `event_id`, a `business_name`, a `contact_email`, a `booth_tier` of `SINGLE` (one space), `DOUBLE` (two contiguous spaces), or `SPONSOR` (three contiguous spaces), and a `power_requested` flag defaulting to false. Creation is not gated on the event's lifecycle. A new application sits in `SUBMITTED`.

Approval prices the booth. Moving `SUBMITTED` → `APPROVED` — permitted while the event is anything but `CLOSED`, else `ERR_INVALID_EVENT_STATE`, and only from `SUBMITTED` itself, else `ERR_INVALID_BOOTH_STATE` — computes the application's `fee_cents` as the tier fee plus a power surcharge: 7,500 cents for `SINGLE`, 14,000 for `DOUBLE`, 25,000 for `SPONSOR`, and exactly 1,500 cents added when `power_requested` is set; the fee is integer cents with no rounding. The organizer may instead move `SUBMITTED` → `REJECTED`, a terminal state; rejection carries no event-state gate.

Payment follows the same exact-amount discipline as entry fees: the vendor (whose `X-User-ID` is the application's `id`) or the organizer records a payment whose `amount_cents` equals the computed `fee_cents`, else `ERR_PAYMENT_AMOUNT_MISMATCH`, while the application is `APPROVED`. Acceptance writes a `BOOTH_FEE` payment, grows the application's `paid_cents`, credits the event treasury (incrementing the event's `version`), and moves the application to `PAID`.

Placement is the final gate. Assigning a booth takes a `zone_id` and a list of `spaces` and requires the application to be `PAID`, else `ERR_INVALID_BOOTH_STATE`. The target zone's `zone_type` must be `VENDOR_ROW` — parking a booth on the show field is rejected with `ERR_ZONE_TYPE_INELIGIBLE`. A power-requesting booth may land only in a zone whose `has_power` is set, else `ERR_POWER_NOT_AVAILABLE`. The `spaces` list must contain exactly as many distinct space integers as the tier demands — one, two, or three — each between 1 and the zone's `capacity` inclusive and forming a contiguous ascending run once sorted (they may arrive in any order); every such violation carries `ERR_BOOTH_SPACES_NOT_CONTIGUOUS`. And no requested space may intersect the `assigned_spaces` of any other `ASSIGNED` application in that zone, else `ERR_BOOTH_SPACE_CONFLICT`. Success sets the application's `assigned_zone_id` and `assigned_spaces`, raises the zone's `assigned_count` by the number of spaces, and lands the application in `ASSIGNED`.

Cancellation — by the organizer, or by the vendor on their own application, with an optional `reason` — is available from `APPROVED`, `PAID`, or `ASSIGNED` and moves the application to terminal `CANCELLED`. When `paid_cents` is above zero, a `REFUND` payment for the full `paid_cents` is written, the event treasury is debited, and `paid_cents` returns to zero. When the application was `ASSIGNED`, its spaces are released — `assigned_zone_id` and `assigned_spaces` are cleared — and the zone's `assigned_count` falls by the number of spaces. Application lists show a `Vendor` only their own application — the one whose `id` equals their `X-User-ID` — while the organizer and the desk see all, filtered by `event_id`, `assigned_zone_id`, or `status`; each application's payment ledger is listable on its own.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource, or add a new resource to a collection, return `201 Created`. Operations that modify an existing resource — including lifecycle transitions, decisions, and state moves — return `200 OK`. The table below is deliberately minimal; request payloads, response shapes, and side effects are specified by the narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/events` | Create a new event in `DRAFT` | Organizer |
| GET    | `/events` | List events, optionally filtered by `lifecycle_status` | Organizer, RegistrationDesk, Participant, Judge, Vendor |
| GET    | `/events/{id}` | Get one event | Organizer, RegistrationDesk, Participant, Judge, Vendor |
| PATCH  | `/events/{id}` | Update event configuration while in `DRAFT` | Organizer |
| POST   | `/events/{id}/publish` | Publish: `DRAFT` → `PUBLISHED` | Organizer |
| POST   | `/events/{id}/open-registration` | `PUBLISHED` → `REGISTRATION_OPEN` | Organizer |
| POST   | `/events/{id}/lock-registration` | `REGISTRATION_OPEN` → `REGISTRATION_LOCKED` | Organizer |
| POST   | `/events/{id}/start-judging` | `REGISTRATION_LOCKED` → `JUDGING`; flips no-shows, creates award rows, may auto-advance | Organizer |
| POST   | `/events/{id}/weather-decision` | Drive `weather_posture`; refunds on `POSTPONED`/`CANCELLED`; `NORMAL` reinstates the permit | Organizer |
| POST   | `/events/{id}/tabulations/finalize` | Compute and finalize award winners (OCC on the event) | Organizer |
| POST   | `/events/{id}/close` | `FINALIZED` → `CLOSED`, or close from any state once cancelled | Organizer |
| GET    | `/events/{id}/summary` | Computed read of event aggregates | Organizer, RegistrationDesk |
| POST   | `/events/{id}/classes` | Create a show class | Organizer |
| GET    | `/events/{id}/classes` | List classes of an event | Organizer, RegistrationDesk, Participant, Judge, Vendor |
| POST   | `/events/{id}/zones` | Create a zone | Organizer |
| GET    | `/events/{id}/zones` | List zones of an event | Organizer, RegistrationDesk, Participant, Judge, Vendor |
| POST   | `/events/{id}/judges` | Roster a judge with assigned classes | Organizer |
| GET    | `/events/{id}/judges` | List judges of an event | Organizer, RegistrationDesk, Participant, Judge, Vendor |
| POST   | `/events/{id}/sound-slots` | Schedule a stage/DJ slot | Organizer |
| GET    | `/events/{id}/sound-slots` | List sound slots, optionally filtered by `status` | Organizer, RegistrationDesk, Participant, Judge, Vendor |
| POST   | `/sound-slots/{id}/cancel` | `SCHEDULED` → `CANCELLED` | Organizer |
| POST   | `/events/{id}/noise-readings` | Record a decibel reading; evaluates curfew and exceedance | Organizer, RegistrationDesk |
| GET    | `/events/{id}/noise-readings` | List noise readings, optionally filtered by `is_exceedance` | Organizer, RegistrationDesk |
| POST   | `/registrants` | Create a participant profile | Participant, RegistrationDesk, Organizer |
| GET    | `/registrants/{id}` | Get a registrant (Participant reads only their own) | Participant, RegistrationDesk, Organizer |
| POST   | `/registrants/{id}/vehicles` | Add a vehicle to a registrant | Participant, RegistrationDesk, Organizer |
| GET    | `/registrants/{id}/vehicles` | List a registrant's vehicles | Participant, RegistrationDesk, Organizer |
| POST   | `/waivers` | Sign a liability waiver for a registrant and event | Participant, RegistrationDesk |
| GET    | `/waivers` | List waivers with filters | Organizer, RegistrationDesk, Participant |
| GET    | `/waivers/{id}` | Get a waiver | Organizer, RegistrationDesk, Participant |
| POST   | `/registrations` | Create a registration; pricing tier and fee are derived and frozen | Participant, RegistrationDesk |
| GET    | `/registrations` | List registrations with filters | Organizer, RegistrationDesk, Participant, Judge |
| GET    | `/registrations/{id}` | Get a registration | Organizer, RegistrationDesk, Participant, Judge |
| POST   | `/registrations/{id}/payments` | Record the entry-fee payment (exact amount) | Participant, RegistrationDesk |
| GET    | `/registrations/{id}/payments` | List a registration's payment ledger | Organizer, RegistrationDesk, Participant |
| POST   | `/registrations/{id}/check-in` | Gate arrival; assigns the lowest free spot in the chosen zone | RegistrationDesk |
| POST   | `/registrations/{id}/withdraw` | Withdraw a registration; refund tier measured from the withdrawal instant | Participant, RegistrationDesk |
| POST   | `/registrations/{id}/refund-decision` | Approve (writes the refund) or deny a refund request | Organizer |
| POST   | `/score-sheets` | Judge creates a `DRAFT` score sheet for a checked-in entry | Judge |
| GET    | `/score-sheets` | List score sheets with filters | Judge, Organizer |
| GET    | `/score-sheets/{id}` | Get a score sheet | Judge, Organizer |
| POST   | `/score-sheets/{id}/submit` | `DRAFT` → `SUBMITTED`; may complete the class and lock all sheets | Judge |
| POST   | `/score-sheets/{id}/reopen` | `SUBMITTED` → `DRAFT` while the event is still judging | Organizer |
| POST   | `/ballots` | Cast a people's-choice ballot | Participant |
| GET    | `/ballots` | List ballots with filters | Organizer, RegistrationDesk |
| GET    | `/ballots/{id}` | Get a ballot | Organizer, RegistrationDesk |
| GET    | `/awards` | List awards with filters | Organizer, RegistrationDesk, Participant, Judge, Vendor |
| GET    | `/awards/{id}` | Get an award | Organizer, RegistrationDesk, Participant, Judge, Vendor |
| POST   | `/awards/{id}/override-winner` | Manually set a winner (OCC plus segregation of duties) | Organizer |
| POST   | `/awards/{id}/present` | `FINALIZED` → `PRESENTED` | Organizer |
| POST   | `/booth-applications` | Create a vendor/sponsor booth application | Organizer |
| GET    | `/booth-applications` | List booth applications (a Vendor sees only their own) | Organizer, Vendor, RegistrationDesk |
| GET    | `/booth-applications/{id}` | Get a booth application | Organizer, Vendor, RegistrationDesk |
| POST   | `/booth-applications/{id}/approve` | `SUBMITTED` → `APPROVED`; computes the booth fee | Organizer |
| POST   | `/booth-applications/{id}/reject` | `SUBMITTED` → `REJECTED` | Organizer |
| POST   | `/booth-applications/{id}/payments` | Record the booth-fee payment (exact amount) | Vendor, Organizer |
| GET    | `/booth-applications/{id}/payments` | List an application's payment ledger | Vendor, Organizer |
| POST   | `/booth-applications/{id}/assign` | `PAID` → `ASSIGNED`; validates zone type, power, contiguity, conflicts | Organizer |
| POST   | `/booth-applications/{id}/cancel` | Cancel an `APPROVED`/`PAID`/`ASSIGNED` application; refunds and releases | Organizer, Vendor |
| POST   | `/_clock/set_current_utc` | Test-driving: set the logical clock; completes elapsed sound slots | Organizer |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows that raise them in §2 and §3; this catalogue is only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_OWNERSHIP_VIOLATION` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_EVENT_STATE` | 409 Conflict |
| `ERR_INVALID_REGISTRATION_STATE` | 409 Conflict |
| `ERR_INVALID_SCORE_SHEET_STATE` | 409 Conflict |
| `ERR_INVALID_BOOTH_STATE` | 409 Conflict |
| `ERR_INVALID_AWARD_STATE` | 409 Conflict |
| `ERR_CLASS_FULL` | 409 Conflict |
| `ERR_ZONE_FULL` | 409 Conflict |
| `ERR_ZONE_TYPE_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_REGISTRATION` | 409 Conflict |
| `ERR_DUPLICATE_BALLOT` | 409 Conflict |
| `ERR_DUPLICATE_SCORE_SHEET` | 409 Conflict |
| `ERR_DUPLICATE_CLASS_CODE` | 409 Conflict |
| `ERR_SOUND_SLOT_OVERLAP` | 409 Conflict |
| `ERR_BOOTH_SPACE_CONFLICT` | 409 Conflict |
| `ERR_BOOTH_SPACES_NOT_CONTIGUOUS` | 422 Unprocessable Entity |
| `ERR_POWER_NOT_AVAILABLE` | 422 Unprocessable Entity |
| `ERR_WAIVER_NOT_SIGNED` | 422 Unprocessable Entity |
| `ERR_GUARDIAN_SIGNATURE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_INSURANCE_POLICY_MISSING` | 422 Unprocessable Entity |
| `ERR_SOUND_PERMIT_SUSPENDED` | 422 Unprocessable Entity |
| `ERR_JUDGING_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_BALLOT_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_OUTSIDE_ARRIVAL_WINDOW` | 422 Unprocessable Entity |
| `ERR_VEHICLE_CLASS_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_JUDGE_NOT_ASSIGNED` | 422 Unprocessable Entity |
| `ERR_JUDGE_CONFLICT_OF_INTEREST` | 422 Unprocessable Entity |
| `ERR_VOTE_INELIGIBLE_CLASS` | 422 Unprocessable Entity |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_REFUND_EXCEEDS_PAID` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 422 Unprocessable Entity |

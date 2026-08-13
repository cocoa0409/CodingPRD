# Historic House Museum Tours API — Product Requirements Document

## 1. Introduction

A historic house museum lives and dies by its guided tours. Rooms are small and fragile, the collection ranges from sturdy period furniture to light-sensitive textiles and high-value objects, and the interpretive program is delivered almost entirely by a volunteer docent corps that must be recruited, trained, certified, and rostered. On any given day the front desk juggles walk-in admissions, members expecting their free-visit benefit, school groups that must satisfy curriculum mandates and chaperone ratios, and the occasional candlelight evening program — all while a curator revises the scripts docents speak from, and while a single safety incident in one room can wipe out an afternoon of departures.

This document specifies the REST API that runs that operation end to end. It covers room and tour-route definition, a cyclic script drafting and accuracy-review workflow with optimistic-concurrency-protected publication, docent training records and threshold-gated certification, per-departure tour slots with finite seat quotas and room-occupancy windowing, shift staffing with a confirmed-lead requirement, three flavors of admission booking (general, member, school) with tiered pricing and time-based refunds, membership lifecycle management, a safety-incident cascade that closes rooms and cancels downstream commitments, and a visitor-survey loop that feeds interpretation improvement. Section 2 fixes the system-wide contracts every endpoint obeys; Section 3 walks the business workflows in narrative form; Section 4 is the endpoint index; Section 5 catalogues the error codes. All endpoints are mounted at the service root.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must present two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. A request missing either header, or presenting a role outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not on the endpoint's authorized list, or that fails an ownership check, is rejected with `ERR_FORBIDDEN` (HTTP 403).

Six roles exist, spelled exactly as follows: `MuseumAdmin`, `Curator`, `DocentCoordinator`, `FrontDeskStaff`, `Docent`, and `Member`. The `MuseumAdmin` is the museum administrator — a superset role with override power over rooms, routes, slots, script publication, and cancellations, and the sole operator of the system-level clock and sweep capabilities. The `Curator` owns collections and interpretation: script submission, review and accuracy scoring, safety-incident resolution, and survey review. The `DocentCoordinator` runs the volunteer program: recruitment, training records, certification, shift assignment and post-visit resolution. The `FrontDeskStaff` role is the visitor-services desk: it books, confirms, and cancels admissions, registers and renews members, advances slots on the day of the visit, and submits surveys on behalf of visitors. A `Docent` confirms or declines their own shift assignments and can report incidents. A `Member` books free admission for themselves, confirms or cancels their own bookings, and submits surveys on their own bookings.

Identity semantics differ by role. When `X-User-Role` is `MuseumAdmin`, `Curator`, `DocentCoordinator`, or `FrontDeskStaff`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any entity's `id`. When `X-User-Role` is `Docent`, `X-User-ID` is the `id` of the acting `Docent`; ownership checks on a shift assignment compare the shift's `docent_id` to `X-User-ID`, so a docent confirming or declining a shift that belongs to someone else is rejected with `ERR_FORBIDDEN`. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on bookings and surveys compare the booking's `member_id` to `X-User-ID`. Additionally, a caller in the `Member` role may only create bookings whose `booking_kind` is `MEMBER` and whose `member_id` equals their own `X-User-ID` — any other creation by a member is rejected with `ERR_FORBIDDEN`.

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

List endpoints accept two query parameters: `limit`, defaulting to 10 with a minimum of 1 and a maximum of 100, and `offset`, defaulting to 0. List responses report `limit`, `offset`, `total_count`, and `has_more` inside `meta`. The default sort order for every list is `created_at` ascending.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource carries a server-minted `id` — a UUID with no type prefix. Resources also carry `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and a `version`, an integer that increments by one on every mutation of the resource; state transitions, administrative edits, and cascade-driven changes all count as mutations. One exception exists: a visitor survey carries only `id` and `created_at`. Both `updated_at` and `version` are absent from surveys, because a survey never changes after submission except for a single review mark.

Two write operations are protected by optimistic concurrency control, and each requires a dedicated non-optional input field carrying the client's last observed `version` of the parent entity:

- Publishing a script requires `expected_route_version`, matched against the parent tour route's current `version`. If the value no longer matches — because the route's version has advanced since the client last read it — the publish is rejected with `ERR_STALE_VERSION` (HTTP 412), and no script pointer is moved.
- Rescheduling a tour slot requires `expected_slot_version`, matched against the slot's current `version`. A mismatch is likewise rejected with `ERR_STALE_VERSION` (HTTP 412), and the slot keeps its existing schedule.

No other write endpoint takes a version field; all other mutations apply immediately against current state.

### 2.5. The Museum's Logical Clock

All time-gated rules in this system — slot scheduling, hold expiries, confirm windows, member lapses, survey windows, incident cascades — read a single museum-wide logical clock, never the server's wall clock. Before it is ever set, the clock's startup default is exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time afterwards. A `MuseumAdmin`-only test-driving capability sets the clock to a supplied `to_iso8601` instant and responds with the resulting `current_utc`. A second `MuseumAdmin`-only capability runs the periodic sweep described in §3.5 and §3.6.

### 2.6. Money, Precision, and Rounding Conventions

All monetary amounts in this API are integer cents: prices, refunds, and revenue figures are never fractional. Wherever a computation produces a fractional cent, the value is rounded half-up to a whole cent. One rounding-order rule is pinned and load-bearing: when a per-person price is scaled (the candlelight multiplier), the per-person amount is rounded half-up to a whole cent first, and only then multiplied by the headcount — never multiply first and round the product. Readiness scores are integers rounded half-up, and survey averages are reported to two decimal places, also rounded half-up.

### 2.7. Collection Tiers and House Safety Rules

Every room belongs to a `collection_tier` of `STANDARD`, `LIGHT_SENSITIVE`, or `HIGH_VALUE`, and the tier drives three house rules. First, the party-cap rule: if any room on a tour route is `HIGH_VALUE`, no single tour party booked onto a slot of that route may exceed the smallest `safety_max_party` among the route's `HIGH_VALUE` rooms; violations are rejected with `ERR_SAFETY_PARTY_TOO_LARGE` (HTTP 422). Second, the candlelight rule: a route whose `kind` is `CANDLELIGHT` may not include any `LIGHT_SENSITIVE` room, and this is enforced at route creation with `ERR_CANDLELIGHT_LIGHT_SENSITIVE` (HTTP 422). Third, the chaperone rule: the free-chaperone quota and the minimum-chaperone requirement for school groups divide by eight instead of ten whenever any room on the route is `HIGH_VALUE` (§3.6). Separately, a `CRITICAL` safety incident closes its room entirely and cascades cancellations (§3.7).

### 2.8. Resource Existence and URL Hierarchy

Path parameters are validated left to right: each `{id}` segment in the URL must resolve to an existing resource before the next segment or the request body is considered, and the first unresolvable segment is rejected with `ERR_NOT_FOUND` (HTTP 404). After the path resolves, identifiers referenced inside the request body — `slot_id`, `member_id`, `docent_id`, `room_id`, and the room or route references carried inside `room_ids` or `route_ids` — must each point at an existing resource, failing which the request is likewise rejected with `ERR_NOT_FOUND`.

### 2.9. Validation Order of Precedence

Every request passes through an ordered gauntlet of checks, and a failure at any tier short-circuits all later tiers — the error surfaced is always the earliest applicable one, never a later mask. The tiers, in evaluation order:

1. **Authentication** — missing or invalid `X-User-Role` or `X-User-ID` headers yield `ERR_UNAUTHENTICATED`.
2. **Authorization and ownership** — the role must be on the endpoint's authorized list, docents act only on their own shifts, members act only on their own bookings and surveys, and the member-creation restriction of §2.1 holds; violations yield `ERR_FORBIDDEN`.
3. **Existence** — path resources left to right, then body identifiers, per §2.8; failures yield `ERR_NOT_FOUND`.
4. **Request shape** — required fields present, enum values inside their declared sets, integer bounds respected (a `party_size` of at least 1 for general and member bookings, `student_count` of at least 1, survey ratings between 1 and 5 inclusive, quiz values between 0 and 100 inclusive, `capacity_max` of at least 1), and kind-specific field-set discipline (a school booking must not carry `party_size`; general and member bookings must not carry the school-only fields); failures yield `ERR_INVALID_REQUEST`.
5. **Lifecycle state** — the target resource must be in a state that offers the requested transition; generic violations yield `ERR_INVALID_STATE`, except booking creation, which has its own code: the slot must be `OPEN`, and any other slot state (including `FULL`) yields `ERR_SLOT_NOT_OPEN`.
6. **Stale versions** — the two optimistic-concurrency fields of §2.4 are checked here; mismatches yield `ERR_STALE_VERSION`.
7. **Collection safety** — the `HIGH_VALUE` party cap (`ERR_SAFETY_PARTY_TOO_LARGE`), the candlelight/light-sensitive prohibition at route creation (`ERR_CANDLELIGHT_LIGHT_SENSITIVE`), and the school chaperone requirement (`ERR_CHAPERONE_RATIO_VIOLATION`).
8. **Threshold gates** — certification thresholds on docent advancement (`ERR_CERTIFICATION_NOT_MET`) and the accuracy floor on script approval (`ERR_REVIEW_SCORE_TOO_LOW`).
9. **Cross-entity references** — slot creation and slot opening require an `ACTIVE` route (`ERR_ROUTE_NOT_ACTIVE`); opening additionally requires a published script (`ERR_SCRIPT_NOT_PUBLISHED`), all rooms open (`ERR_ROOM_CLOSED`), and a confirmed lead (`ERR_SLOT_NOT_STAFFED`); shift assignment checks docent qualification (`ERR_DOCENT_NOT_QUALIFIED`); school bookings check curriculum alignment (`ERR_CURRICULUM_NOT_ALIGNED`); route retirement checks for future slots (`ERR_ROUTE_HAS_FUTURE_SLOTS`).
10. **Temporal rules** — slot creation and reschedule times must lie in the future (`ERR_SLOT_IN_PAST`); docent shift windows must not collide under the buffer rule (`ERR_SHIFT_OVERLAP`); room occupancy windows must not collide (`ERR_ROOM_OCCUPANCY_CONFLICT`); booking confirmation must precede the tour start (`ERR_CONFIRM_WINDOW_CLOSED`); surveys must arrive within the post-visit window (`ERR_SURVEY_WINDOW_CLOSED`).
11. **Capacity and fiscal rules, last** — seats remaining (`ERR_CAPACITY_EXCEEDED`), the single-lead rule (`ERR_LEAD_ALREADY_ASSIGNED`), member standing (`ERR_MEMBER_NOT_ACTIVE`), payment equality (`ERR_PAYMENT_MISMATCH`), and one survey per booking (`ERR_DUPLICATE_SURVEY`).

Because ordering matters, a booking that violates both the chaperone requirement and the seat capacity is rejected with `ERR_CHAPERONE_RATIO_VIOLATION`, not `ERR_CAPACITY_EXCEEDED`; a publish carrying both a stale version and an otherwise invalid payload reports the stale version first.

### 2.10. Snapshot Fields and Live Computed Fields

Some figures are frozen at the instant of creation and never recomputed afterwards, while others are recomputed on every relevant mutation and on read. A tour slot's `capacity` is a snapshot taken at slot creation; later edits to a room's `capacity_max` do not retroactively change existing slots. A booking's `unit_price_cents` and `total_price_cents` are likewise frozen at booking creation. By contrast, a slot's `seats_reserved`, `seats_confirmed`, `seats_available`, `revenue_committed_cents`, `revenue_projected_cents`, and `staffing_status` are live aggregates, recomputed after every booking or shift mutation touching the slot, and a docent's `readiness_standard_score` and `readiness_apprentice_score` are recomputed on read and whenever a training record lands. All consistency is immediate: every cascade and derived-field update settles within the triggering request, so a response always reflects the full downstream effect of the operation.

## 3. Business Logic & Workflows

### 3.1. Mapping the House: Rooms and Tour Routes

Before anything can be scheduled, a `MuseumAdmin` maps the building. Each room is registered with a display `name` (for example, "East Parlor"), a `floor` number, a `capacity_max` giving the maximum persons physically allowed in the room at once (at least 1), a `safety_max_party` giving the largest single tour party admitted under collection-safety rules (at least 1), and its `collection_tier`. A new room starts in `OPEN` status; its only other state, `CLOSED_RESTORATION`, is reached exclusively through the incident cascade of §3.7. Any authenticated role may read a room, list the routes that visit it, and — for `MuseumAdmin` and `Curator` — list its incident history.

Routes are the museum's tour products. A `MuseumAdmin` creates one with a `name` (for example, "Main Floor Highlights"), a `kind` of `STANDARD`, `SCHOOL`, or `CANDLELIGHT`, an ordered `room_ids` array containing at least one room (each referenced room must exist, and the order determines the per-room occupancy windows of §3.4), a `duration_minutes` of at least 10, and a `base_price_cents` of zero or more. The candlelight prohibition of §2.7 bites here: a `CANDLELIGHT` route naming a `LIGHT_SENSITIVE` room is rejected with `ERR_CANDLELIGHT_LIGHT_SENSITIVE`. New routes begin in `DRAFT` with `published_script_id` null — a route with no published script cannot field open slots. Activation moves a route from `DRAFT` to `ACTIVE` and increments the route's `version`. Retirement moves an `ACTIVE` route to its terminal `RETIRED` state, but only when no slot of the route sits in `SCHEDULED`, `OPEN`, or `FULL` with a `start_at` still in the future; attempting retirement with such future departures fails with `ERR_ROUTE_HAS_FUTURE_SLOTS` (HTTP 409). Retirement, like activation, increments the route's `version`. The route catalog list accepts an optional `published_script_id` filter that finds the route whose currently published script is the given script version, and a route's slot list accepts an optional `status` filter alongside standard pagination.

### 3.2. The Interpretation Cycle: Script Drafting, Accuracy Review, and Publication

Interpretation lives in versioned scripts. A `Curator` (or a `MuseumAdmin`) opens a new draft under a route by supplying `content_text` — the docent's spoken interpretation — and `curriculum_standards`, an array of curriculum standard codes (such as HIST-5 or CIV-3) the script is aligned to, which may be empty. Each draft is stamped with a `version_no` that is monotonic per route: the route's first script receives 1, and every later draft receives the next number, one more than the highest existing `version_no` on that route. A fresh draft sits in `DRAFT`, where it may be edited freely.

Submission moves a script from `DRAFT` to `IN_REVIEW` and is a `Curator` action; it increments the script's `version`. Review is also a `Curator` action and takes a `decision` with optional `accuracy_score` and `reviewer_notes`. Three branches leave `IN_REVIEW`, and each behaves differently. With `decision` APPROVE, the `accuracy_score` must be provided and must be at least 80 — anything lower, or a missing score, is rejected with `ERR_REVIEW_SCORE_TOO_LOW` (HTTP 422) — and on success the score and notes are recorded on the script as it moves to `APPROVED`. With `decision` REQUEST_REVISION, no score is required; the script returns to `DRAFT` for another editing cycle with its `version_no` unchanged, and this draft–review–revision loop may repeat indefinitely. With `decision` REJECT, the script moves to `REJECTED`, a terminal state. Every review, whatever the decision, increments the script's `version`.

Publication is the `MuseumAdmin`'s lever and the point where the route's public product changes. Publishing an `APPROVED` script must carry `expected_route_version` per the optimistic-concurrency rule of §2.4; a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing changes. On success, three things happen atomically: the route's `published_script_id` is set to the newly published script, the route's `version` increments by one, and any previously `PUBLISHED` script of the same route is moved by the system to `SUPERSEDED`. Both `REJECTED` and `SUPERSEDED` are terminal. Downstream, only the route's currently published script matters: school bookings validate their requested `curriculum_standard` against its `curriculum_standards` (§3.6), and slot opening refuses to proceed while `published_script_id` is null (§3.4).

### 3.3. Growing the Docent Roster: Recruitment, Training, and Certification

The `DocentCoordinator` recruits each docent with a `full_name` and an `email`, unique per docent. A new docent starts as an `APPLICANT` with `training_hours` at 0, `shadow_tours_completed` at 0, and `quiz_score` null until the first quiz lands.

Training is logged as records carrying a `kind` and a `value`. An HOURS record adds `value` to `training_hours`. A SHADOW_TOUR record requires `value` to be exactly 1 and increments `shadow_tours_completed`. A QUIZ record carries a `value` between 0 and 100 inclusive and sets `quiz_score` to the latest result. Every training record recomputes both readiness scores.

Two readiness scores travel with the docent, reported on every read of the docent record and recomputed at the certification check. Both share the same three inputs: the hours term is `training_hours` capped at 30 hours and then divided by 30; the shadow term is `shadow_tours_completed` capped at 5 and divided by 5; the quiz term is `quiz_score` divided by 100, treating a null quiz as zero. The `readiness_standard_score` weights those terms at three-tenths hours, three-tenths shadow, and four-tenths quiz; the weighted sum is multiplied by 100 and rounded half-up to an integer between 0 and 100. The `readiness_apprentice_score` uses the identical inputs with weights of one-half hours, four-tenths shadow, and one-tenth quiz — the same data, a different number — and is reported alongside the standard score but never gates certification.

Advancement is requested with a `to_status`. Moving an `APPLICANT` to `TRAINEE` has no threshold. Moving a `TRAINEE` to `CERTIFIED` is threshold-gated on all four fronts: `training_hours` of at least 20, `shadow_tours_completed` of at least 3, a `quiz_score` of at least 85, and a `readiness_standard_score` of at least 70 — failing any one rejects the advance with `ERR_CERTIFICATION_NOT_MET` (HTTP 422). The certification request must also carry a non-empty `route_ids` array, which becomes the docent's `certified_route_ids`, the routes they are qualified to lead. Each advancement increments the docent's `version`.

Deactivation moves a `TRAINEE` or `CERTIFIED` docent to the terminal `INACTIVE` state, increments the docent's `version`, and ripples outward in two hops within the same request: first, every shift assignment of this docent still in `ASSIGNED` or `CONFIRMED` whose slot starts after the logical clock is cancelled; second, each affected slot recomputes its `staffing_status`, so a `STAFFED` slot that loses its only confirmed lead drops to `UNSTAFFED`.

### 3.4. Building the Tour Calendar: Slots, Staffing, and the Day of the Visit

A `MuseumAdmin` creates a tour slot by naming a `route_id` and a `start_at`. The `start_at` must lie strictly after the logical clock — a slot created at or before the present is rejected with `ERR_SLOT_IN_PAST` (HTTP 422) — and the route must be `ACTIVE`, failing which the create is rejected with `ERR_ROUTE_NOT_ACTIVE` (HTTP 409). At creation the slot is stamped `SCHEDULED`, its `end_at` is computed as `start_at` plus the route's `duration_minutes`, both `seats_reserved` and `seats_confirmed` start at zero, `seats_available` equals the snapshotted `capacity`, both revenue fields start at zero, and `staffing_status` evaluates to `UNSTAFFED` until shifts arrive.

The slot's `capacity` is a creation-time snapshot, never recomputed afterwards. It is the smallest `capacity_max` among all rooms on the route — every room in `room_ids` participates regardless of whether it is currently open, because room closure is enforced separately at slot-open time — minus a buffer determined by the route's `kind`: two seats for a `STANDARD` route, zero for a `SCHOOL` route, and four for a `CANDLELIGHT` route. If that subtraction would drop the figure below one, the capacity floors at one. Later edits to any room's `capacity_max` leave existing slots untouched.

Creation also runs the room-occupancy conflict check, and the same check runs again on every reschedule. The route's rooms are visited in the order given by `room_ids`; dividing `duration_minutes` by the number of rooms and rounding down to a whole minute yields the per-room slice, and the leftover minutes — the duration minus the slices — are absorbed by the final room. The first room is therefore occupied from `start_at` until `start_at` plus one slice, the second from there until `start_at` plus two slices, and so on, with the last room occupied from its slice boundary all the way to `end_at`. Two slots conflict exactly when their routes share at least one room and that room's occupancy windows overlap under half-open semantics: the windows overlap only when each window's start is strictly before the other window's end, and windows that merely touch — one ending exactly as the other begins — do not conflict. Only slots in `SCHEDULED`, `OPEN`, `FULL`, or `IN_PROGRESS` participate in this check; `CANCELLED` and `COMPLETED` slots occupy nothing. A genuine collision is rejected with `ERR_ROOM_OCCUPANCY_CONFLICT` (HTTP 409).

Staffing begins when the `DocentCoordinator` assigns a docent to a slot with a `shift_role` of `LEAD` or `SHADOW`, supplying `docent_id` and `slot_id`. Qualification is checked against the slot's route: a `LEAD` must be `CERTIFIED` with that route present in `certified_route_ids`, while a `SHADOW` need only be `TRAINEE` or `CERTIFIED`; an unqualified assignment is rejected with `ERR_DOCENT_NOT_QUALIFIED` (HTTP 422). A slot may carry at most one non-terminal `LEAD` assignment — a second lead while one is still `ASSIGNED` or `CONFIRMED` is rejected with `ERR_LEAD_ALREADY_ASSIGNED` (HTTP 409). The double-booking guard rejects any assignment where the docent already holds a non-terminal shift whose slot window, padded by a thirty-minute buffer, conflicts with the candidate slot's window; the rejection is `ERR_SHIFT_OVERLAP` (HTTP 409). A fresh assignment sits in `ASSIGNED`, and the slot's `staffing_status` recomputes on every shift change: `STAFFED` when a `CONFIRMED` `LEAD` shift exists, `NEEDS_LEAD` when a non-terminal `ASSIGNED` `LEAD` exists but none is confirmed, and `UNSTAFFED` otherwise.

Docents answer for themselves. Confirming moves a shift from `ASSIGNED` to `CONFIRMED`, and declining moves it from `ASSIGNED` to `DECLINED`; both require the caller's `X-User-ID` to equal the shift's `docent_id`, else `ERR_FORBIDDEN`. A lead's confirmation is what flips a slot from `UNSTAFFED` or `NEEDS_LEAD` to `STAFFED`; declines recompute staffing as well. After the visit, the `DocentCoordinator` resolves each `CONFIRMED` shift with an `outcome` of `COMPLETED` or `NO_SHOW` — but only once the slot itself is `COMPLETED`; resolving earlier is rejected with `ERR_INVALID_STATE` (HTTP 409). Shifts are also cancelled by the system, from either `ASSIGNED` or `CONFIRMED`, when their slot is cancelled, when a room closure cascades, or when the docent is deactivated, and every such cancellation recomputes the slot's staffing.

Opening a slot is a `MuseumAdmin` action guarded by four gates, each with its own error: the route must be `ACTIVE` (`ERR_ROUTE_NOT_ACTIVE`), the route must have a published script — `published_script_id` non-null (`ERR_SCRIPT_NOT_PUBLISHED`, HTTP 409), every room on the route must be `OPEN` (`ERR_ROOM_CLOSED`, HTTP 409), and the slot must be `STAFFED` with a confirmed lead (`ERR_SLOT_NOT_STAFFED`, HTTP 409). Passing all four moves the slot from `SCHEDULED` to `OPEN` and increments the slot's `version`. From there the system manages the seat pool: when a booking creation or confirmation drives `seats_available` to exactly zero the slot flips from `OPEN` to `FULL`, and when a cancellation or expiry frees seats it flips back from `FULL` to `OPEN` — a cycle that may repeat any number of times, with `seats_available` never going negative.

On the day of the visit, `MuseumAdmin` or `FrontDeskStaff` advances the slot. Requesting `to_status` IN_PROGRESS moves an `OPEN` or `FULL` slot to `IN_PROGRESS`, but only once the logical clock has reached `start_at`; starting early is rejected with `ERR_INVALID_STATE`. Requesting `to_status` COMPLETED then moves the slot from `IN_PROGRESS` to `COMPLETED`, which is terminal. Completion unlocks two downstream activities: the slot's `CONFIRMED` shifts may now be resolved, and surveys open for its `CONFIRMED` bookings (§3.8). Each advance increments the slot's `version`.

A `MuseumAdmin` may cancel a slot from `SCHEDULED`, `OPEN`, or `FULL`. The cancellation cascades in the same request: every booking of the slot in `RESERVED` or `CONFIRMED` is cancelled — confirmed bookings receive the time-tier refund of §3.6 on a manual cancellation — and every shift in `ASSIGNED` or `CONFIRMED` is cancelled, after which staffing recomputes and the slot's `version` increments.

Rescheduling moves a slot's `start_at` while the slot is `SCHEDULED` or `OPEN`; attempting it from any other state is rejected with `ERR_INVALID_STATE`. The request carries the new `start_at`, which must lie strictly after the logical clock (`ERR_SLOT_IN_PAST`), and `expected_slot_version` under the optimistic-concurrency rule of §2.4, with mismatches rejected as `ERR_STALE_VERSION` (HTTP 412). A successful reschedule recomputes `end_at` from the new start, re-runs the room-occupancy check against the new windows (`ERR_ROOM_OCCUPANCY_CONFLICT`), re-runs the thirty-minute-buffer overlap check for the docents already rostered on the slot (`ERR_SHIFT_OVERLAP`), and increments the slot's `version`.

### 3.5. Membership Standing and Renewal

`MuseumAdmin` or `FrontDeskStaff` registers a member with `full_name`, `email`, a unique external `member_number`, and a `renews_on` calendar date in YYYY-MM-DD form. New members start `ACTIVE`.

Membership ages under the periodic sweep, a `MuseumAdmin`-only ops capability that also expires stale booking holds (§3.6) and reports the sweep's results as `expired_booking_count` and `lapsed_member_count`. On each run, an `ACTIVE` member whose `renews_on` has passed — the renewal date is earlier than the current date — slips to `LAPSED`, and a `LAPSED` member more than thirty days past `renews_on` hardens into `EXPIRED`, which is terminal.

Renewal restores standing: from either `ACTIVE` or `LAPSED`, a renewal carrying a `renews_on` strictly after the current date moves the member back to `ACTIVE` and replaces the stored date. A renewal date that is not strictly in the future is rejected with `ERR_INVALID_REQUEST` (HTTP 400), and an `EXPIRED` member cannot be renewed at all — the transition is not offered from that state and fails with `ERR_INVALID_STATE`. Renewal increments the member's `version`. Standing matters downstream because only an `ACTIVE` member's booking earns the free seat of §3.6.

### 3.6. Admission Bookings: Reservations, Pricing, Payment, and Refunds

Bookings are created by `MuseumAdmin`, `FrontDeskStaff`, or `Member`. Every creation supplies `slot_id`, a `booking_kind` of `GENERAL`, `MEMBER`, or `SCHOOL`, and a `visitor_name` for the lead visitor or school contact. The kind dictates the field set, and the discipline is enforced as request validation with `ERR_INVALID_REQUEST` (HTTP 400): `GENERAL` and `MEMBER` bookings carry a `party_size` of at least 1 — for members the member themselves is included in the count — and must not pass the school-only fields `student_count`, `chaperone_count`, `grade_level`, or `curriculum_standard`; `SCHOOL` bookings are the mirror image, forbidden from passing `party_size` (their party size is computed as `student_count` plus `chaperone_count`) and instead carrying a `student_count` of at least 1, a `chaperone_count` of zero or more, a `grade_level`, and a `curriculum_standard`. The `member_id` is required and non-null exactly when `booking_kind` is `MEMBER` and must be absent for the other kinds, and per §2.1 a caller in the `Member` role may create only `MEMBER` bookings naming themselves.

Creation then faces the business guards, in the precedence order of §2.9. The slot must be `OPEN` — a `FULL` slot is already a failed state for new bookings, and any non-open slot yields `ERR_SLOT_NOT_OPEN` (HTTP 409). The collection-safety checks follow: the `HIGH_VALUE` party cap of §2.7 rejects oversized parties with `ERR_SAFETY_PARTY_TOO_LARGE`, and a school group must meet its chaperone quota — the required number of chaperones is the `student_count` divided by ten and rounded up to a whole chaperone, tightening to a divisor of eight when any room on the route is `HIGH_VALUE`, and the booking passes when `chaperone_count` is at least the requirement, with an exact match counting as a pass — else `ERR_CHAPERONE_RATIO_VIOLATION` (HTTP 422). The requested `curriculum_standard` must appear among the `curriculum_standards` of the route's currently `PUBLISHED` script, else `ERR_CURRICULUM_NOT_ALIGNED` (HTTP 422). Capacity comes last: the `party_size` must not exceed the slot's `seats_available`, though a party exactly equal to the remaining seats is allowed; overcapacity is rejected with `ERR_CAPACITY_EXCEEDED` (HTTP 409). A `MEMBER` booking also requires the member to be `ACTIVE`; booking with a `LAPSED` or `EXPIRED` member is rejected with `ERR_MEMBER_NOT_ACTIVE` (HTTP 422).

Pricing is computed and frozen on the booking at the instant of creation, in integer cents under the rounding rules of §2.6. For `GENERAL`, the per-person unit is the route's `base_price_cents`, except on a `CANDLELIGHT` route, where the unit is one and a half times the base, rounded half-up to a whole cent per person before anything is multiplied; the booking's `unit_price_cents` records that per-person figure, and `total_price_cents` is the unit multiplied by `party_size` — round per person first, then multiply by headcount, never the reverse. For `MEMBER`, the unit is computed exactly as for `GENERAL`, candlelight multiplier included, but the member's own seat is free, so `total_price_cents` is the unit multiplied by `party_size` minus one; a solo active member therefore pays zero. For `SCHOOL`, students are charged in tiers — the first fifteen students at 800 cents each, the next fifteen (students sixteen through thirty) at 700 cents each, and every student beyond the thirtieth at 600 cents each — and chaperones are free up to the same rounded-up quota used by the chaperone requirement (divisor ten, or eight with a `HIGH_VALUE` room on the route), with each chaperone beyond the free quota costing 1000 cents; `total_price_cents` is the student charge plus the extra-chaperone charge, and because school pricing is a group rate, `unit_price_cents` on a school booking carries that group total rather than a per-person figure.

A fresh booking sits in `RESERVED`. Creation immediately adds its `party_size` to the slot's `seats_reserved`, flips the slot from `OPEN` to `FULL` if `seats_available` reaches zero, and recomputes the slot's revenue. The hold is finite: `hold_expires_at` is set to the earlier of two instants — 48 hours after the booking's creation, and the slot's `start_at` — and the periodic sweep expires any `RESERVED` booking whose `hold_expires_at` the logical clock has reached, moving it to `EXPIRED`, releasing its reserved seats, flipping a `FULL` slot back to `OPEN` when seats are freed, and recomputing revenue.

Confirmation converts a hold into a sale. The booking must be `RESERVED` — confirming anything else is rejected with `ERR_INVALID_STATE` — its slot must be `OPEN` or `FULL`, and the logical clock must still be strictly before the slot's `start_at`; confirming at or after the start is rejected with `ERR_CONFIRM_WINDOW_CLOSED` (HTTP 422). The request carries `paid_cents`, which must equal the booking's `total_price_cents` exactly; any discrepancy is rejected with `ERR_PAYMENT_MISMATCH` (HTTP 422). On success the booking moves to `CONFIRMED`, its `party_size` leaves `seats_reserved` and joins `seats_confirmed`, the slot flips to `FULL` if the seats now available reach zero, and revenue recomputes. Members confirm their own bookings; the desk and admin confirm anyone's.

Cancellation releases seats from whichever bucket the booking occupied — reserved or confirmed — and sets `refund_cents`, which is zero until the moment of cancellation. A `RESERVED` booking always refunds zero, as does any booking that paid zero, such as a solo member visit. Cancelling a paid `CONFIRMED` booking follows the time tiers measured in whole hours between the logical clock and the slot's `start_at`: at least 48 hours before the start, the full `total_price_cents` is refunded; at least 24 hours but fewer than 48, half the total is refunded, rounded half-up to a whole cent; fewer than 24 hours, nothing is refunded. Cancellations forced by the incident cascade of §3.7 bypass the tiers entirely and refund the full total. Freeing seats flips a `FULL` slot back to `OPEN`, and revenue recomputes either way. Cancellation is available to `MuseumAdmin`, `FrontDeskStaff`, and the owning member.

Two revenue aggregates ride on every slot read. `revenue_committed_cents` is the sum of `total_price_cents` over the slot's `CONFIRMED` bookings — money actually confirmed, nothing more. `revenue_projected_cents` adds a forward-looking uplift to the same committed base: the sum of `total_price_cents` over the slot's `RESERVED` bookings, multiplied by 0.8 and rounded half-up to a whole cent. `CANCELLED` and `EXPIRED` bookings are excluded from both figures, always.

### 3.7. Collection Safety Incidents and the Closure Cascade

Anyone on the floor can report an incident: `MuseumAdmin`, `Curator`, `FrontDeskStaff`, and `Docent` are all authorized. A report names the `room_id` where it happened, an optional `slot_id` identifying the tour in progress at the time, a `severity` of `MINOR`, `MAJOR`, or `CRITICAL`, and a free-text `description`. Every report opens in `REPORTED`.

Severity decides the blast radius. `MINOR` and `MAJOR` reports are logged without closing anything. A `CRITICAL` report, however, fires a three-hop cascade that settles within the same request. Hop one: the room moves from `OPEN` to `CLOSED_RESTORATION`. Hop two: every slot whose route contains that room, sitting in `SCHEDULED`, `OPEN`, or `FULL`, and whose `start_at` is still after the logical clock, is cancelled. Hop three: for each such slot, its bookings in `RESERVED` or `CONFIRMED` are cancelled — confirmed bookings refunded in full, bypassing the time tiers — and its shift assignments in `ASSIGNED` or `CONFIRMED` are cancelled, with staffing recomputed.

Resolution is a `MuseumAdmin` or `Curator` action moving the incident from `REPORTED` to the terminal `RESOLVED`. When a resolved incident was `CRITICAL`, the room reopens from `CLOSED_RESTORATION` to `OPEN` only if no other `REPORTED` `CRITICAL` incident still references the same room; while another critical report remains open against it, the room stays closed.

### 3.8. Visitor Surveys and Interpretation Improvement

After the visit, feedback arrives through surveys submitted by the member who owns the booking — ownership compares the caller's `X-User-ID` to the booking's `member_id` — or by `FrontDeskStaff` on a visitor's behalf. The booking must be `CONFIRMED` and its slot must be `COMPLETED`; surveying a booking whose slot has not completed is rejected with `ERR_INVALID_STATE`. The window closes fourteen days after the slot's completion, and a later submission is rejected with `ERR_SURVEY_WINDOW_CLOSED` (HTTP 422). One survey per booking is the rule; a second submission for the same booking is rejected with `ERR_DUPLICATE_SURVEY` (HTTP 409).

A survey carries an `overall_rating` between 1 and 5 inclusive, an `interpretation_clarity` between 1 and 5 inclusive, a boolean `would_recommend`, and an optional free-text `comment`. Its `booking_id` is taken from the creation path and its `slot_id` is derived from the booking's slot. New surveys sit in `SUBMITTED`, and per §2.4 a survey carries only `id` and `created_at` — no `updated_at`, no `version`. The interpretation-improvement loop closes when a `Curator` reviews a survey, moving it from `SUBMITTED` to `REVIEWED`.

Route-level aggregation turns individual responses into signal. The survey summary for a route counts every survey whose slot belongs to that route, in either `SUBMITTED` or `REVIEWED` status, and reports `survey_count` alongside `avg_overall_rating` and `avg_interpretation_clarity` — the arithmetic means of the two rating fields, each rounded half-up to two decimal places. When a route has no surveys at all, the count is 0 and both averages are 0.0.

## 4. Endpoint Definitions

Endpoints that create a new resource respond with HTTP 201; reads, state transitions, and all other modifications respond with HTTP 200. The table below is an index only — request payloads, computed fields, and side effects are specified by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST | /rooms | Create a room | MuseumAdmin |
| GET | /rooms/{id} | Get a room | MuseumAdmin, Curator, DocentCoordinator, FrontDeskStaff, Docent, Member |
| GET | /rooms/{id}/routes | List routes whose `room_ids` contain this room | MuseumAdmin, Curator, DocentCoordinator, FrontDeskStaff, Docent, Member |
| GET | /rooms/{id}/incidents | List safety incidents for this room | MuseumAdmin, Curator |
| POST | /tour-routes | Create a route (starts `DRAFT`) | MuseumAdmin |
| GET | /tour-routes | List routes; optional `published_script_id` filter finds the route whose current published script is the given script version | MuseumAdmin, Curator, DocentCoordinator, FrontDeskStaff, Docent, Member |
| GET | /tour-routes/{id} | Get a route | MuseumAdmin, Curator, DocentCoordinator, FrontDeskStaff, Docent, Member |
| POST | /tour-routes/{id}/activate | Move a route from `DRAFT` to `ACTIVE` | MuseumAdmin |
| POST | /tour-routes/{id}/retire | Move a route from `ACTIVE` to `RETIRED`; requires no future non-cancelled slots | MuseumAdmin |
| GET | /tour-routes/{id}/script-versions | List script versions for this route | MuseumAdmin, Curator, DocentCoordinator, FrontDeskStaff, Docent, Member |
| GET | /tour-routes/{id}/tour-slots | List slots for this route; optional `status` filter, paginated | MuseumAdmin, Curator, DocentCoordinator, FrontDeskStaff, Docent, Member |
| GET | /tour-routes/{id}/survey-summary | Aggregated visitor survey metrics for the route | MuseumAdmin, Curator |
| GET | /tour-routes/{id}/docents | List docents certified on this route | MuseumAdmin, DocentCoordinator |
| POST | /tour-routes/{id}/script-versions | Create a script draft for the route; `version_no` assigned monotonically per route | Curator, MuseumAdmin |
| GET | /script-versions/{id} | Get a script version | MuseumAdmin, Curator, DocentCoordinator, FrontDeskStaff, Docent, Member |
| POST | /script-versions/{id}/submit | Move a script from `DRAFT` to `IN_REVIEW` | Curator |
| POST | /script-versions/{id}/review | Review a script: APPROVE (accuracy floor applies), REQUEST_REVISION, or REJECT | Curator |
| POST | /script-versions/{id}/publish | Publish an `APPROVED` script; supersedes the route's prior published script (OCC on route version) | MuseumAdmin |
| POST | /tour-slots | Create a slot (`SCHEDULED`); snapshots capacity and checks room-occupancy conflicts | MuseumAdmin |
| GET | /tour-slots/{id} | Get a slot with computed seat, revenue, and staffing fields | MuseumAdmin, Curator, DocentCoordinator, FrontDeskStaff, Docent, Member |
| POST | /tour-slots/{id}/open | Move a slot from `SCHEDULED` to `OPEN` (route active, script published, rooms open, confirmed lead) | MuseumAdmin |
| POST | /tour-slots/{id}/advance | Advance a slot to `IN_PROGRESS` or `COMPLETED` | MuseumAdmin, FrontDeskStaff |
| POST | /tour-slots/{id}/cancel | Cancel a slot; cascades bookings (time-tier refunds) and shifts | MuseumAdmin |
| POST | /tour-slots/{id}/reschedule | Change a slot's `start_at` (while `SCHEDULED` or `OPEN`); recomputes `end_at`, re-checks conflicts (OCC on slot version) | MuseumAdmin |
| GET | /tour-slots/{id}/bookings | List bookings for a slot | MuseumAdmin, FrontDeskStaff |
| GET | /tour-slots/{id}/shifts | List shift assignments for a slot | MuseumAdmin, DocentCoordinator, Docent |
| GET | /tour-slots/{id}/incidents | List safety incidents referencing a slot | MuseumAdmin, Curator |
| GET | /tour-slots/{id}/surveys | List surveys for a slot | MuseumAdmin, Curator, DocentCoordinator, FrontDeskStaff, Docent, Member |
| POST | /docents | Recruit a docent (starts `APPLICANT`) | DocentCoordinator |
| GET | /docents/{id} | Get a docent with readiness scores | MuseumAdmin, DocentCoordinator, Docent |
| POST | /docents/{id}/advance | Advance a docent toward `TRAINEE` or `CERTIFIED` (thresholds and `route_ids` apply at certification) | DocentCoordinator |
| POST | /docents/{id}/deactivate | Deactivate a docent; future shifts cancel and affected slots recompute staffing | DocentCoordinator |
| POST | /docents/{id}/training-records | Log a training record (hours, shadow tour, or quiz) | DocentCoordinator |
| GET | /docents/{id}/shifts | List a docent's shift assignments | MuseumAdmin, DocentCoordinator, Docent |
| POST | /shift-assignments | Assign a docent to a slot as `LEAD` or `SHADOW` | DocentCoordinator |
| POST | /shift-assignments/{id}/confirm | Docent confirms their own shift | Docent |
| POST | /shift-assignments/{id}/decline | Docent declines their own shift | Docent |
| POST | /shift-assignments/{id}/resolve | Resolve a confirmed shift as `COMPLETED` or `NO_SHOW` after the slot completes | DocentCoordinator |
| POST | /members | Register a member (starts `ACTIVE`) | MuseumAdmin, FrontDeskStaff |
| GET | /members/{id} | Get a member | MuseumAdmin, FrontDeskStaff, Member |
| POST | /members/{id}/renew | Renew a member with a new future `renews_on` | MuseumAdmin, FrontDeskStaff |
| GET | /members/{id}/bookings | List a member's bookings | MuseumAdmin, FrontDeskStaff, Member |
| POST | /bookings | Create a booking (`RESERVED`); pricing, safety, chaperone, curriculum, and capacity checks apply | MuseumAdmin, FrontDeskStaff, Member |
| GET | /bookings/{id} | Get a booking | MuseumAdmin, FrontDeskStaff, Member |
| POST | /bookings/{id}/confirm | Confirm a reserved booking; `paid_cents` must equal `total_price_cents`, before the slot starts | MuseumAdmin, FrontDeskStaff, Member |
| POST | /bookings/{id}/cancel | Cancel a booking; time-tier refund, seats released | MuseumAdmin, FrontDeskStaff, Member |
| POST | /bookings/{id}/surveys | Submit a survey for a confirmed booking whose slot completed (within fourteen days); one per booking | Member, FrontDeskStaff |
| GET | /bookings/{id}/surveys | List surveys for a booking (zero or one) | MuseumAdmin, Curator, DocentCoordinator, FrontDeskStaff, Docent, Member |
| POST | /surveys/{id}/review | Curator marks a survey `REVIEWED` | Curator |
| POST | /safety-incidents | Report a safety incident; `CRITICAL` closes the room and cascades cancellations | MuseumAdmin, Curator, FrontDeskStaff, Docent |
| POST | /safety-incidents/{id}/resolve | Resolve an incident; reopens the room when no other open critical incident references it | MuseumAdmin, Curator |
| POST | /_clock/set_current_utc | Set the museum's logical clock | MuseumAdmin |
| POST | /_ops/run_epoch | Run the periodic sweep: expire stale booking holds, lapse and expire members | MuseumAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this table is an index of identifiers to HTTP status codes.

| Error ID | HTTP Status Code |
|----------|------------------|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_SLOT_NOT_OPEN | 409 |
| ERR_ROUTE_NOT_ACTIVE | 409 |
| ERR_ROUTE_HAS_FUTURE_SLOTS | 409 |
| ERR_SCRIPT_NOT_PUBLISHED | 409 |
| ERR_ROOM_CLOSED | 409 |
| ERR_SLOT_NOT_STAFFED | 409 |
| ERR_SAFETY_PARTY_TOO_LARGE | 422 |
| ERR_CHAPERONE_RATIO_VIOLATION | 422 |
| ERR_CURRICULUM_NOT_ALIGNED | 422 |
| ERR_CANDLELIGHT_LIGHT_SENSITIVE | 422 |
| ERR_DOCENT_NOT_QUALIFIED | 422 |
| ERR_SHIFT_OVERLAP | 409 |
| ERR_ROOM_OCCUPANCY_CONFLICT | 409 |
| ERR_SLOT_IN_PAST | 422 |
| ERR_CONFIRM_WINDOW_CLOSED | 422 |
| ERR_SURVEY_WINDOW_CLOSED | 422 |
| ERR_CAPACITY_EXCEEDED | 409 |
| ERR_LEAD_ALREADY_ASSIGNED | 409 |
| ERR_MEMBER_NOT_ACTIVE | 422 |
| ERR_PAYMENT_MISMATCH | 422 |
| ERR_CERTIFICATION_NOT_MET | 422 |
| ERR_REVIEW_SCORE_TOO_LOW | 422 |
| ERR_DUPLICATE_SURVEY | 409 |

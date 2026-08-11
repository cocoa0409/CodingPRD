# Renaissance Faire API — Product Requirements Document

## 1. Introduction

A Renaissance faire lives and dies by its season. Between an opening day and a closing day, the operator must book cast and hold rehearsals, jury artisans and food vendors into booth residencies, sell day passes, season passes, and group admissions, staff the gate and the tavern with volunteers, and stand ready to cancel a day when the weather turns — issuing rain checks, crediting vendors, and paying cast a reduced weather rate without losing the thread of who is owed what. Beside that core loop sit the less glamorous obligations: health permits for anyone selling food or drink, a costume-and-conduct policy with real sanctions, and a site that must be built before the gates open and struck after they close.

This document specifies the API that runs that operation as a single system of record. The Season is the organizing aggregate: it carries a computed readiness posture that gates when ticket sales may open and when the season itself may open, and it accumulates the counters — confirmed volunteer hours, outstanding admissions — that later events must conserve. Alongside the Season, parallel state machines govern cast contracts, vendor applications, booth assignments, food permits, ticket orders, tickets, rain checks, volunteer shifts, conduct cases, and build tasks, with cascades that keep the season's counters and postures honest whenever weather, conduct, or inspection events land. All money moves in integer cents under pinned rounding rules, all temporal gates evaluate against a server-side logical clock, and two editing surfaces are guarded by optimistic concurrency so that clients never reprice or reconfigure from a stale base.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes ten role designators: `FaireOperator`, `CastDirector`, `VendorCoordinator`, `GateAgent`, `VolunteerCoordinator`, `Performer`, `Vendor`, `Volunteer`, `Guest`, and `Any`. An attempt to perform an operation outside the caller's permitted set is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403), and where a workflow declares resource ownership, a caller whose identity does not match the owner is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). The designator `Any` confers shared read access: every authenticated role may call any GET endpoint, whether a list or a single-resource read.

Two roles are entity-backed. When `X-User-Role` is `Performer`, `X-User-ID` is the `id` of the acting Performer; ownership checks on any resource that references a Performer compare the resource's foreign-key field to `X-User-ID` — concretely, a performer may counter or accept only the cast contract whose `performer_id` equals their `X-User-ID`. When `X-User-Role` is `Vendor`, `X-User-ID` is the `id` of the acting Vendor; filing an application stamps the application's `vendor_id` from `X-User-ID`, and later ownership checks on appeals, withdrawals, booth confirmations, and permit applications compare the linked application's `vendor_id` to `X-User-ID`.

The remaining roles are opaque. When `X-User-Role` is `FaireOperator`, `CastDirector`, `VendorCoordinator`, `GateAgent`, or `VolunteerCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, and the server does not compare it to any entity's `id`. When `X-User-Role` is `Volunteer`, `X-User-ID` is an opaque handle; the server records it as `volunteer_handle` on each shift the volunteer signs up for and compares it to that recorded handle — never to an entity `id` — when the volunteer later cancels their own shift. When `X-User-Role` is `Guest`, `X-User-ID` is the buyer's email; the server records it as `buyer_email` on each order the guest creates and compares it to that recorded value when the guest edits, pays, or redeems a rain check sourced from the order.

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

List endpoints are paginated through two query parameters. The `limit` parameter specifies the maximum number of items to return; when omitted it defaults to 10, and it accepts a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

All fifteen resources of this API — Season, FaireDay, Performer, CastContract, RehearsalSlot, Vendor, VendorApplication, BoothAssignment, FoodPermit, TicketOrder, Ticket, RainCheck, VolunteerShift, ConductCase, and BuildTask — share one set of system-managed fields:

- `id` (string): a server-minted UUID, with no type prefix, assigned at creation.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every change to the resource's properties.
- `version` (integer): starts at 1 when the resource is created and increments by 1 on every mutation. System-driven changes count as mutations: when a cascade or a recomputation updates a derived counter such as a season's `outstanding_admissions` or `volunteer_confirmed_hours`, that season's `updated_at` is refreshed and its `version` incremented like any other edit.

### 2.5. The Logical Clock, Calendar Dates, and Lazy Expiration

All temporal gates in this API evaluate against a server-side logical clock, never against wall-clock time. An operator-only test-driving capability — restricted to `FaireOperator` — sets the logical clock to a supplied `to_iso8601` instant and answers with the resulting `current_utc`. Before any such call, the clock's startup default is exactly 2026-05-01T00:00:00Z, and once set it never falls back to wall-clock time; it may be set to any ISO 8601 instant. The weather-call deadline, the rain-check redemption window, permit validity, and the rule that gates may open only on a faire day's own calendar date all read this clock.

Calendar-boundary fields — a faire day's `date`, a season's `opening_date` and `closing_date`, and booth residency boundaries — are midnight-UTC instants (00:00:00Z) naming a calendar day. Residency and scheduling overlap rules use half-open intervals throughout: an interval includes its start and excludes its end, so one residency or shift may begin at the exact instant another ends without conflict.

Two expirations are lazy rather than timer-driven. A food permit whose `expiry_date` has passed becomes `EXPIRED` the next time the permit is read or written, or the next time the season's readiness posture is re-derived; a rain check whose `redeem_by_date` has passed becomes `EXPIRED` on its next read or write, and any still outstanding are swept when the season closes. Both transitions evaluate against the logical clock, so advancing the clock and then touching the resource is enough to surface the expiry.

### 2.6. Season Readiness Posture

Every season carries a computed `readiness_posture` of `BLOCKED`, `CONDITIONAL`, or `READY`, re-derived from the season's own records whenever relevant facts change. The derivation is evaluated in exactly this order. If any BuildTask of the season with `phase` `BUILD` has a `status` other than `DONE`, the posture is `BLOCKED`. Otherwise, the posture is `CONDITIONAL` when either of the following holds: some application of the season is `JURIED_IN` for a vendor whose `category` is `FOOD` or `BEVERAGE` yet has no food permit of the same application in `ISSUED` status with an `expiry_date` on or after the current clock instant; or the season's `volunteer_confirmed_hours` is strictly below its `volunteer_min_hours`. If none of those conditions hold, the posture is `READY`. The volunteer threshold is inclusive at the boundary: confirmed hours exactly equal to `volunteer_min_hours` satisfy it and permit `READY`. Hours are compared exactly, at two decimal places.

The `volunteer_confirmed_hours` figure itself is the sum of `hours` over the season's volunteer shifts whose `status` is `CONFIRMED` or `WORKED`; shifts in any other status contribute nothing. Posture is re-derived whenever one of its inputs moves: build-task creation and advancement, volunteer-shift confirmation, close-out, and cancellation (including the weather-cancellation cascade), jury decisions, food-permit issuance, revocation, and expiry, and booth suspension. It is also re-derived when the season moves from `PLANNING` to `BUILD`, and immediately before either outward gate below evaluates it, so both gates always act on the current derivation rather than a previously stored value. Two outward gates read the posture: opening the season requires `READY`, and opening sales on any faire day is forbidden while the posture is `BLOCKED`.

### 2.7. Money, Integer Cents, and Rounding Discipline

All monetary values are integer numbers of cents; the API never carries fractional cents. Where a calculation produces a fractional result, it is rounded half up — a discarded fraction of exactly half a cent rounds away from zero — and each rule pins where that rounding happens. An order's discounted base is rounded half up to whole cents once, before any per-ticket fee is added, so the fee itself is never rounded. A booth's daily weather credit is rounded half up to whole cents for each cancelled day before being accumulated; rounding the season-long aggregate once at the end is a rejected alternative, because the two orders of operations yield different cent totals. A prime-booth settlement surcharge is rounded half up once at settlement. A cast rehearsal-shortfall penalty is rounded half up once, and each weather-day payout line is rounded half up individually as it accrues. The one non-integer figure in the system is the jury score, which is rounded half up to two decimal places.

### 2.8. Optimistic Concurrency Control

Two editing surfaces carry optimistic concurrency control, and only those two; no other endpoint accepts a version field.

Editing a season's configuration requires the request to carry `expected_season_version`, a non-optional field holding the season's `version` as the client last observed it. If the season's current `version` has advanced beyond that value, the edit is rejected with `ERR_STALE_VERSION` (HTTP 412). A configuration edit keeps the season in `PLANNING`, so without this check a later edit based on a previously observed version would silently rebase thresholds — capacity, group size, volunteer hours — onto a configuration the caller never saw.

Editing an unpaid ticket order requires the analogous `expected_order_version`, matched against the order's current `version`; a mismatch is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). The order remains `UNPAID` across edits, so a later edit carrying a previously observed version would otherwise reprice from a stale base.

On both surfaces the version check sits inside the state-validation layer: it is evaluated only after every state precondition of the operation has passed, so a stale version on an otherwise valid request surfaces `ERR_STALE_VERSION`, while a request that also violates a state rule surfaces that state error first.

### 2.9. Validation Order and Resource Existence

When several checks could reject the same request, the server evaluates them in a fixed nine-layer order, and the first failing layer determines the error returned:

1. **Header presence.** `X-User-ID` and `X-User-Role` must both be present and non-empty on every request, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).
2. **Authorization.** The caller's role must be permitted for the endpoint, else `ERR_UNAUTHORIZED_ROLE` (HTTP 403); where ownership is declared, the caller must own the resource, else `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
3. **Existence.** Resource identifiers in the path are validated left to right, and the first missing one produces its resource-specific 404: `ERR_SEASON_NOT_FOUND`, `ERR_FAIRE_DAY_NOT_FOUND`, `ERR_PERFORMER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_BOOTH_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_RAIN_CHECK_NOT_FOUND`, `ERR_SHIFT_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, or `ERR_TASK_NOT_FOUND`. Only after the path resolves are foreign keys in the request body — `season_id`, `faire_day_id`, `contract_id`, `application_id`, `performer_id`, `target_faire_day_id`, every entry of `depends_on_task_ids`, `linked_order_id`, and `linked_permit_id` — checked against the same 404 family.
4. **Request shape.** Required fields must be present; types, enum memberships, and ranges must be valid — end times strictly after their start times, `closing_date` on or after `opening_date`, `quantity` at least 1, fraction fields between 0 and 1 inclusive, jury scores between 0 and 10 inclusive; a `SEASON` order must omit `faire_day_id` while `DAY` and `GROUP` orders must include it; unknown fields are rejected. All shape failures return `ERR_INVALID_REQUEST` (HTTP 400).
5. **State gates.** The target resources must be in the states the operation requires. Where a transition declares several preconditions they are evaluated in the order this document lists them, so the first failing gate's state-specific 409 is the one returned. The two optimistic-concurrency version checks described in §2.8 are evaluated after all state preconditions within this layer.
6. **Food-safety gate.** Confirming a booth for a `FOOD` or `BEVERAGE` vendor requires an `ISSUED`, unexpired food permit on the same application, else `ERR_FOOD_PERMIT_NOT_ISSUED` (HTTP 409).
7. **Clock-relative gates.** Weather cancellation before the day's deadline hour (`ERR_WEATHER_CALL_TOO_LATE`), rain-check redemption on or before `redeem_by_date` (`ERR_RAIN_CHECK_EXPIRED`), gate opening only on the faire day's own calendar date (`ERR_DAY_NOT_TODAY`), and operations that require an `OPERATING` day (`ERR_DAY_NOT_OPERATING`) — all HTTP 409.
8. **Constraint layer.** Rehearsal-stage buffered overlap (`ERR_REHEARSAL_OVERLAP`), booth-site half-open overlap (`ERR_BOOTH_OVERLAP`), same-volunteer shift overlap (`ERR_VOLUNTEER_SHIFT_OVERLAP`), one active application per vendor per season (`ERR_DUPLICATE_APPLICATION`), one active booth assignment per application (`ERR_APPLICATION_ALREADY_BOOKED`), one active permit per application (`ERR_DUPLICATE_PERMIT`), build-task dependency cycles (`ERR_TASK_DEPENDENCY_CYCLE`) and unmet dependencies (`ERR_TASK_DEPENDENCY_UNMET`), day admission capacity (`ERR_DAY_AT_CAPACITY`), and the group minimum size (`ERR_GROUP_SIZE_BELOW_MINIMUM`). Every layer-8 failure is HTTP 409 except `ERR_GROUP_SIZE_BELOW_MINIMUM`, which is HTTP 422.
9. **Fiscal bounds.** A refund's `refund_cents` must be positive and must not exceed the order's `retained_cents` (`ERR_REFUND_EXCEEDS_PAID`, HTTP 422), and a refund is permitted only while the order's redemption status allows one (`ERR_NOTHING_REFUNDABLE` or `ERR_ORDER_NOT_REFUNDABLE`, both HTTP 409).

### 2.10. Conserved Ledgers: Admissions and Refund Money

Two invariants hold at all times and define how the season's counters move.

A season's `outstanding_admissions` equals the count of its tickets in `VALID` status plus the count of its rain checks in `ISSUED` status. The figure is conserved across each compensating pair: a weather cancellation converts one `VALID` ticket into one `ISSUED` rain check for a net change of zero, and a rain-check redemption consumes one `ISSUED` check while minting one `VALID` ticket, again net zero. It is deliberately not conserved on four events: paying an order adds its `quantity`, voiding a ticket subtracts one, a ticket's expiry subtracts one, and a rain check's expiry subtracts one.

Within a ticket order, money is conserved: `refunded_cents` plus `retained_cents` always equals `total_cents`. Every refund adds its amount to `refunded_cents` and recomputes `retained_cents` as the total minus what has been refunded, and no refund may exceed the `retained_cents` that remain.

## 3. Business Logic & Workflows

### 3.1. Season Setup, Site Build, and the Road to Opening Day

A `FaireOperator` opens a new season by supplying its `name`, its `opening_date` and `closing_date` (the closing date must be on or after the opening date), the `daily_capacity` bounding day-ticket admissions per faire day (at least 1), the `group_min_size` that defines a group booking (at least 2), the `volunteer_min_hours` of confirmed volunteer time the season needs before it can be called ready (zero or more), the `weather_call_deadline_hour` fixing how late into a faire day a weather cancellation may be called (a whole-hour offset between 0 and 23 inclusive), and the `rain_check_grace_days` for which rain checks remain redeemable after the season ends (zero or more). A new season begins with `status` `PLANNING`, `readiness_posture` initialized to `BLOCKED`, `volunteer_confirmed_hours` and `outstanding_admissions` at zero, `version` at 1, and `season_weeks` computed as the number of days from opening to closing divided by seven and rounded up to a whole number of weeks — the figure booth fees later multiply against.

While the season remains in `PLANNING`, the operator may revise its configuration — `daily_capacity`, `group_min_size`, `volunteer_min_hours`, `weather_call_deadline_hour`, and `rain_check_grace_days` — through the OCC-guarded edit described in §2.8, which requires `expected_season_version` and increments the season's `version` by 1 on success. If `volunteer_min_hours` changes, the readiness posture is re-derived against the new threshold. Once the season has left `PLANNING`, configuration edits are rejected with `ERR_SEASON_NOT_IN_PLANNING`.

Site work is organized as build tasks. The operator creates each task with a `season_id`, a `phase` of `BUILD` or `STRIKE`, a `name`, and optionally a `depends_on_task_ids` list naming same-season tasks that must finish first. `BUILD`-phase tasks may be created while the season is `PLANNING` or `BUILD`; `STRIKE`-phase tasks may be created while the season is `PLANNING`, `BUILD`, `OPEN`, or `STRIKE`; against any other season state the creation fails with `ERR_SEASON_INVALID_STATE`. The dependency list must reference existing tasks of the same season and must never introduce a cycle — an addition that would close a dependency loop, whether at creation or when later extending a non-terminal task's dependencies via `add_task_ids`, is rejected with `ERR_TASK_DEPENDENCY_CYCLE`. A new task starts `PENDING`, and creating one immediately re-derives the season's posture, since an unfinished `BUILD`-phase task blocks readiness. A reverse-lookup listing answers which tasks declare a given task in their own `depends_on_task_ids`. Advancing a task moves it `PENDING` → `IN_PROGRESS` → `DONE` under the `to` parameter: the step into `IN_PROGRESS` is allowed only from `PENDING` and only when every task in `depends_on_task_ids` is already `DONE` (otherwise `ERR_TASK_DEPENDENCY_UNMET`); the step into `DONE` is allowed only from `IN_PROGRESS`; any other pairing of current state and `to` is rejected with `ERR_TASK_NOT_ADVANCEABLE`. Completing a `BUILD`-phase task re-derives the posture, which may unblock the season.

Two transitions carry the season toward its run. Beginning the build moves `PLANNING` → `BUILD` and is rejected from any other state with `ERR_SEASON_NOT_IN_PLANNING`; the transition re-derives the readiness posture per §2.6. Opening the season moves `BUILD` → `OPEN`: it requires the season to be in `BUILD` (else `ERR_SEASON_INVALID_STATE`) and, the posture having been re-derived per §2.6 after that state check, the readiness posture to be `READY` (else `ERR_SEASON_NOT_READY`). Upon opening, every cast contract of the season sitting in `ACCEPTED` or `REHEARSING` whose `completed_rehearsal_hours` has reached its `required_rehearsal_hours` moves automatically to `PERFORMING`, and the posture is re-derived one final time.

### 3.2. Cast Contracts, Rehearsals, and Performer Pay

Casting begins when a `CastDirector` registers a performer with a `stage_name`, an `act_type` of `MUSIC`, `COMBAT`, `COMEDY`, `ACROBATICS`, or `ROVING`, and a `base_day_rate_cents` of zero or more as the reference day rate.

The director then drafts a cast contract naming the `season_id` and `performer_id` and proposing commercial terms: `offered_day_rate_cents`, the number of `guaranteed_days` with guaranteed pay (zero or more), the `weather_pay_pct` fraction of the day rate paid for a weather-cancelled day (between 0 and 1 inclusive), and the `required_rehearsal_hours` the performer must log before performing (zero or more). The season must be `PLANNING` or `BUILD`, else the creation is rejected with `ERR_SEASON_INVALID_STATE`. A fresh contract is `DRAFT` with `negotiation_round` at 0, `countered_day_rate_cents` still null, `completed_rehearsal_hours` and `accrued_payout_cents` at zero, and `final_payout_cents` not yet set.

Negotiation alternates between the two parties. An offer by the director moves the contract from `DRAFT` or `COUNTERED` to `OFFERED` — from any other state it fails with `ERR_CONTRACT_NOT_OFFERABLE` — and is permitted only while the season remains `PLANNING` or `BUILD` (else `ERR_SEASON_INVALID_STATE`); each offer increments `negotiation_round` by 1, and when the director offers again from `COUNTERED` while omitting `offered_day_rate_cents` from the payload, the offer adopts the performer's `countered_day_rate_cents` as the new offered rate. A counter by the owning performer — whose `X-User-ID` must equal the contract's `performer_id`, else `ERR_NOT_RESOURCE_OWNER` — moves `OFFERED` → `COUNTERED`, stores the payload's `countered_day_rate_cents`, and increments `negotiation_round` by 1; from any state other than `OFFERED` a counter fails with `ERR_CONTRACT_NOT_OFFERED`. Acceptance by the owning performer moves `OFFERED` → `ACCEPTED` under the same state and ownership gates, leaving the offered rate as the agreed day rate.

Rehearsals are scheduled by the director as slots carrying a `contract_id`, a `stage_name` identifying the rehearsal stage resource, a `start_time`, and an `end_time` that must be strictly later than the start (a range violation returns `ERR_INVALID_REQUEST`). The contract must be `ACCEPTED` or `REHEARSING`, else `ERR_CONTRACT_NOT_REHEARSABLE`. Each slot is treated as occupying its stage from its start until fifteen minutes after its end — a trailing turnover buffer — and a new slot whose own start-to-fifteen-minutes-after-end window intersects the occupancy window of an existing `SCHEDULED` or `ATTENDED` slot on the same stage is rejected with `ERR_REHEARSAL_OVERLAP`. A new slot stands `SCHEDULED` with `hours_credit` zero.

Attendance recording by the director takes an `outcome` against a `SCHEDULED` slot (else `ERR_SLOT_NOT_RECORDABLE`). An `ATTENDED` outcome sets the slot's `hours_credit` to its duration in hours — the difference between `end_time` and `start_time` — adds that credit to the contract's `completed_rehearsal_hours`, and, if the contract was still `ACCEPTED`, moves it automatically to `REHEARSING`. A `NO_SHOW` outcome leaves `hours_credit` at zero and teaches the contract nothing. A slot may instead be cancelled outright while `SCHEDULED` (else `ERR_SLOT_NOT_CANCELLABLE`), moving it to `CANCELLED`; the same cancellation lands automatically on every still-`SCHEDULED` slot of a contract that is terminated.

Performer pay accrues chronologically as faire days resolve. When a faire day completes, every contract of the season in `PERFORMING` at that moment adds its full `offered_day_rate_cents` to `accrued_payout_cents`. When a faire day is cancelled for weather, every contract in `ACCEPTED`, `REHEARSING`, or `PERFORMING` at that moment adds its weather rate: the `offered_day_rate_cents` multiplied by the contract's `weather_pay_pct`, rounded half up to whole cents for that day. Day events apply in the order they occur, and each event touches a contract at most once per day.

Termination by the director is available from any non-terminal state — `DRAFT`, `OFFERED`, `COUNTERED`, `ACCEPTED`, `REHEARSING`, or `PERFORMING` — and from a terminal state fails with `ERR_CONTRACT_NOT_TERMINABLE`. Termination moves the contract to `TERMINATED` and sets `final_payout_cents` to the `accrued_payout_cents` recorded so far: no guarantee floor applies and no rehearsal penalty is charged. Contracts that survive to the season's strike are instead completed (see §3.9) and settled at the guarantee floor: the final payout is the greater of `accrued_payout_cents` and `guaranteed_days` times `offered_day_rate_cents`, minus a rehearsal-shortfall penalty. The shortfall is the amount by which `required_rehearsal_hours` exceeds `completed_rehearsal_hours`, treated as zero when the requirement was met; each short hour costs 5,000 cents, with the penalty rounded half up to whole cents once, and the resulting `final_payout_cents` is floored at zero so a settlement can never go negative.

### 3.3. Vendor Jury, Booth Booking, and Residency

A `VendorCoordinator` registers each vendor with a `business_name` and a `category` of `FOOD`, `BEVERAGE`, `ARTISAN`, or `GAMES`. From there the vendor drives their own application.

Filing an application requires the season to be in `PLANNING` — the jury window closes once building begins, and a filing against any other season state is rejected with `ERR_SEASON_NOT_IN_PLANNING`. The vendor supplies the `season_id`, the requested `booth_size_sqft` (at least 1), and a `requested_location_tier` of `PRIME`, `STANDARD`, or `MEADOW`; the server stamps `vendor_id` from the caller's `X-User-ID`. A vendor may hold only one non-terminal application per season, so a second filing while an earlier one is still live fails with `ERR_DUPLICATE_APPLICATION`. The application opens in `JURY_REVIEW` with `appeal_used` false and `jury_score` still null.

A jury decision by the coordinator records three criterion scores — `craft_score`, `authenticity_score`, and `safety_score`, each between 0 and 10 — together with an `outcome` of `JURIED_IN`, `JURIED_OUT`, or `WAITLISTED`. The application must currently be in `JURY_REVIEW`, `APPEALED`, or `WAITLISTED`; deciding from any other state fails with `ERR_APPLICATION_NOT_DECIDABLE`. On every decision the scores are stored and the `jury_score` is computed as half the craft score plus three-tenths of the authenticity score plus one-fifth of the safety score, rounded half up to two decimal places. A decision of `JURIED_IN` additionally re-derives the season's readiness posture, because a juried-in food or beverage vendor now needs an issued health permit before the season can be called ready.

A vendor whose application lands in `JURIED_OUT` may appeal it exactly once. The appeal requires the application to be `JURIED_OUT` (else `ERR_APPLICATION_NOT_APPEALABLE`), requires `appeal_used` to still be false (a second attempt fails with `ERR_APPEAL_ALREADY_USED`), and requires the caller to own the application (else `ERR_NOT_RESOURCE_OWNER`); it moves the application to `APPEALED` and sets `appeal_used` true. From `APPEALED` the coordinator may decide again under the same rules as above, with fresh scores stored and the `jury_score` recomputed. Withdrawal is the vendor's own exit: from `JURY_REVIEW`, `APPEALED`, `JURIED_OUT`, or `WAITLISTED` — any non-terminal state, else `ERR_APPLICATION_NOT_WITHDRAWABLE` — the owning vendor may withdraw, moving the application to its terminal `WITHDRAWN` state.

Once an application is `JURIED_IN`, the coordinator reserves a booth for it, supplying the `application_id`, a `booth_site` identifier, and the `residency_start_date` and `residency_end_date` bounding the residency as a half-open interval — the end must be strictly after the start. The application must indeed be `JURIED_IN` (else `ERR_APPLICATION_NOT_JURIED_IN`), the season must be `PLANNING` or `BUILD` (else `ERR_SEASON_INVALID_STATE`), the application must not already hold a non-terminal booth assignment (else `ERR_APPLICATION_ALREADY_BOOKED`), and the new residency must not intersect any existing one on the same `booth_site`; because intervals are half-open, a residency may begin on the exact day another ends, but any true overlap is rejected with `ERR_BOOTH_OVERLAP`. The reservation copies `season_id` from the application and quotes a `provisional_fee_cents` that assumes a full season with zero weather days and zero surcharges: the `booth_size_sqft` multiplied by the tier rate — 120 cents per square foot per week for `PRIME`, 80 for `STANDARD`, 50 for `MEADOW` — multiplied by the season's `season_weeks`. The assignment opens `RESERVED` with `weather_credit_cents` at zero.

Confirmation belongs to the vendor who owns the linked application (else `ERR_NOT_RESOURCE_OWNER`) and moves the booth from `RESERVED` or `SUSPENDED` to `CONFIRMED` — from any other state it fails with `ERR_BOOTH_NOT_CONFIRMABLE`. For vendors whose `category` is `FOOD` or `BEVERAGE`, confirmation is gated on health compliance: a food permit of the same application must exist in `ISSUED` status with an `expiry_date` on or after the current clock instant, else the confirmation is rejected with `ERR_FOOD_PERMIT_NOT_ISSUED`. A successful confirmation commits the provisional fee as paid.

Release by the coordinator is available only from `RESERVED` (else `ERR_BOOTH_NOT_RELEASEABLE`) and moves the booth to `RELEASED`. Releasing a booth triggers waitlist promotion for the season: among applications currently `WAITLISTED`, the top candidate by `jury_score` descending — applications without a score rank last — with ties broken by earliest `created_at`, is promoted automatically to `JURIED_IN`; when no application is waiting, the release simply stands.

### 3.4. Food and Beverage Health Permits

Any vendor whose application is `JURIED_IN` and whose vendor `category` is `FOOD` or `BEVERAGE` may apply for a health permit against that application; the caller must own the application. Applying against an application in any other state fails with `ERR_APPLICATION_NOT_JURIED_IN`, applying for a vendor of any other category fails with `ERR_PERMIT_NOT_APPLICABLE`, and applying while the application already holds a non-terminal permit fails with `ERR_DUPLICATE_PERMIT` — only one live permit may exist per application. A new permit stands `APPLIED` with `inspection_attempts` at zero and `permit_number` still null.

Inspections are recorded by the coordinator with an `outcome` of `PASSED` or `FAILED`, and the permit must be `APPLIED` or `AWAITING_REINSPECTION`, else `ERR_PERMIT_NOT_INSPECTIONABLE`. Every recorded inspection increments `inspection_attempts` by 1. A `PASSED` outcome moves the permit to `ISSUED`: a server-minted `permit_number` is assigned, the `expiry_date` is set to the season's `closing_date` plus a fixed system grace period of additional days, and the season's readiness posture is re-derived. A `FAILED` outcome branches on the attempt count: when the attempt just recorded is not the final permitted one — the post-increment count remains below the system's fixed maximum number of inspection attempts — the permit moves to `AWAITING_REINSPECTION`, but when the recorded attempt is the last permitted one the permit lands in its terminal `FAILED_FINAL` state.

Revocation by the coordinator requires an `ISSUED` permit (else `ERR_PERMIT_NOT_REVOKABLE`) and moves it to `REVOKED`. Expiry is lazy per §2.5: once the clock passes `expiry_date`, the permit becomes `EXPIRED` on its next read or write or on the next posture re-derivation — note that at exactly `expiry_date` the permit still counts as valid, since the booth-confirmation gate accepts an expiry on or after now. Either event fires the same cascade: every booth assignment of the same application currently `CONFIRMED` drops to `SUSPENDED`, and the season's readiness posture is re-derived, since a juried-in food application no longer holds an issued permit. Suspension is not the end of the road: once the application again holds an `ISSUED`, unexpired permit, the vendor may re-confirm the booth under the rules of §3.3.

### 3.5. Ticket Orders, Group Pricing, and Payment

A `Guest` places a ticket order by naming the `season_id`, an `order_type` of `DAY`, `SEASON`, or `GROUP`, a `quantity` of at least 1, a `unit_price_cents` of zero or more, and — for `DAY` and `GROUP` orders only — the `faire_day_id` of the day to attend. The shape rule is strict: `DAY` and `GROUP` orders must include `faire_day_id`, a `SEASON` order must omit it, and any violation is an `ERR_INVALID_REQUEST`. The server stamps `buyer_email` from the caller's `X-User-ID`. For `DAY` and `GROUP` orders the named faire day must already be `OPEN_FOR_SALES`, else `ERR_DAY_NOT_OPENABLE`; a `SEASON` order instead requires the season itself to be in `BUILD` or `OPEN`, else `ERR_SEASON_INVALID_STATE`. A `GROUP` order must also clear the season's group threshold — a `quantity` below the season's `group_min_size` is rejected with `ERR_GROUP_SIZE_BELOW_MINIMUM` (HTTP 422).

Pricing is computed at placement. The base is the `quantity` multiplied by the `unit_price_cents`. Group orders earn a discount keyed to how the `quantity` compares with the season's `group_min_size`: reaching the group minimum earns a ten-percent discount, reaching at least twice the minimum earns fifteen percent, and reaching at least four times the minimum earns twenty percent — the applied fraction is recorded as the order's `discount_pct`. `DAY` and `SEASON` orders are never discounted. For `DAY` orders only, a convenience fee of 150 cents per ticket is charged on top. The order's `total_cents` is the base multiplied by one minus the discount fraction, rounded half up to whole cents, plus the convenience fee — the rounding lands on the discounted base before the fee is added, never on the fee. A new order stands with `payment_status` `UNPAID` and `redemption_status` `UNREDEEMED`, `refunded_cents` at zero, and `retained_cents` equal to the full `total_cents`.

While an order remains `UNPAID`, the buyer may revise its `quantity` or its `faire_day_id` through the OCC-guarded edit of §2.8, which requires `expected_order_version` and increments the order's `version` by 1 on success; editing an order in any other payment state is rejected with `ERR_ORDER_NOT_UNPAID`, and every successful edit reprices the order exactly as at placement, recomputing `discount_pct`, `total_cents`, and `retained_cents`.

Payment is the buyer's own act — the caller's `X-User-ID` must equal the order's `buyer_email`, else `ERR_NOT_RESOURCE_OWNER` — and requires the order to be `UNPAID`, else `ERR_ORDER_NOT_UNPAID`. For `DAY` and `GROUP` orders the faire day's capacity gate applies: minting the order's tickets must keep the day's `tickets_sold_count` — the count of that day's tickets in `VALID` or `REDEEMED` status — plus the order's `quantity` at or below the season's `daily_capacity`, else the payment is rejected with `ERR_DAY_AT_CAPACITY`. On success the order becomes `PAID` and `quantity` tickets are minted in `VALID` status, each carrying the order's `order_id`: `DAY` and `GROUP` orders mint `ticket_type` `DAY` tickets bound to the order's `faire_day_id`, while `SEASON` orders mint `ticket_type` `SEASON` passes whose `faire_day_id` is null. The season's `outstanding_admissions` grows by the `quantity` minted.

Refunds are processed by a `GateAgent` supplying a positive `refund_cents`. The order's payment status must be `PAID` or `PARTIALLY_REFUNDED` — an `UNPAID` or `REFUNDED` order fails with `ERR_ORDER_NOT_UNPAID`. Two redemption-state gates follow: a `FULLY_REDEEMED` order has nothing left to refund and fails with `ERR_NOTHING_REFUNDABLE`, while a `RAINCHECKED` or `VOID` order fails with `ERR_ORDER_NOT_REFUNDABLE`. Finally the amount is bounded by what the order retains: a `refund_cents` exceeding `retained_cents` is rejected with `ERR_REFUND_EXCEEDS_PAID` (HTTP 422). A successful refund adds to `refunded_cents` and recomputes `retained_cents`, preserving the money invariant of §2.10; when the refund falls short of the remaining retained amount the order becomes `PARTIALLY_REFUNDED`, and when it equals that amount exactly the order becomes `REFUNDED`.

An order's `redemption_status` tracks its tickets automatically as they change state. When a ticket of an `UNREDEEMED` order is redeemed while others remain `VALID`, the order becomes `PARTIALLY_REDEEMED`; when the last `VALID` ticket of an order is redeemed — including the single-ticket order whose only ticket redeems — the order becomes `FULLY_REDEEMED`. A weather cancellation that rain-checks every ticket of an order moves it from `UNREDEEMED` to `RAINCHECKED`, and a conduct ban voids tickets into the `VOID` state as described in §3.9.

### 3.6. Running a Faire Day: Sales, Gates, Completion, and Weather Cancellation

The operator schedules each faire day against a `season_id` and a `date` that must fall within the season's `opening_date` to `closing_date` span inclusive — a date outside the season is an `ERR_INVALID_REQUEST` — while the season is `PLANNING` or `BUILD`, else `ERR_SEASON_INVALID_STATE`. The day opens in `SCHEDULED` with `tickets_sold_count` at zero.

Opening sales moves the day `SCHEDULED` → `OPEN_FOR_SALES` (from any other state, `ERR_DAY_NOT_OPENABLE`) and is gated on the season twice over: the season must be in `BUILD` or `OPEN` (else `ERR_SEASON_INVALID_STATE`), and its readiness posture — re-derived per §2.6 before this gate is evaluated — must not be `BLOCKED` (else `ERR_SEASON_POSTURE_BLOCKED`). Weather management then brackets the sales window: placing the day on weather hold moves `OPEN_FOR_SALES` → `WEATHER_HOLD` (else `ERR_DAY_NOT_HOLDABLE`), and releasing the hold returns `WEATHER_HOLD` → `OPEN_FOR_SALES` (else `ERR_DAY_NOT_ON_HOLD`).

On the morning of the day itself, opening the gates moves `OPEN_FOR_SALES` → `OPERATING`. The day must be in `OPEN_FOR_SALES` (else `ERR_DAY_NOT_OPENABLE`), the season must be `OPEN` (else `ERR_SEASON_NOT_OPEN`), and the logical clock's calendar date must equal the day's `date` (else `ERR_DAY_NOT_TODAY`). Completing the day moves `OPERATING` → `COMPLETED`: the day must be `OPERATING` (else `ERR_DAY_NOT_COMPLETABLE`) and every volunteer shift of the day must already stand in a terminal state — `WORKED`, `NO_SHOW`, or `CANCELLED` — else `ERR_OPEN_SHIFTS_EXIST`. Completion settles the day's books: every still-`VALID` `DAY` ticket of the day expires to `EXPIRED`, decrementing the season's `outstanding_admissions` by one per expired ticket, and every contract of the season in `PERFORMING` accrues its full `offered_day_rate_cents` per the payout rules of §3.2.

Weather cancellation is the day's exceptional exit, callable from `OPEN_FOR_SALES` or `WEATHER_HOLD` — from any other state it fails with `ERR_DAY_NOT_CANCELLABLE` — and only before the day's deadline: the call must land strictly before the day's `date` plus the season's `weather_call_deadline_hour` hours, and a call at or after that instant is rejected with `ERR_WEATHER_CALL_TOO_LATE`. A successful call moves the day to `CANCELLED_WEATHER` and fires a five-part cascade. First, every `VALID` ticket of the day with `ticket_type` `DAY` becomes `RAINCHECKED`, and one rain check in `ISSUED` status is created per such ticket, stamped with the season's `season_id`, the source `ticket_id`, and the cancelled day as `issued_for_day_id`, with `redeem_by_date` set to the season's `closing_date` plus its `rain_check_grace_days` days; each owning order's `redemption_status` is recomputed, becoming `RAINCHECKED` when all of its tickets now stand rain-checked, while the season's `outstanding_admissions` does not move — each `VALID` ticket converts one-for-one into an `ISSUED` check. Second, every volunteer shift of the day in `SIGNED_UP` or `CONFIRMED` is cancelled, and the season's `volunteer_confirmed_hours` is recomputed with the hours of the cancelled `CONFIRMED` shifts removed. Third, the readiness posture is re-derived from the new confirmed-hours figure. Fourth, cast payout accrues at the weather rate per §3.2 for every contract in `ACCEPTED`, `REHEARSING`, or `PERFORMING`. Fifth, every booth assignment of the season in `RESERVED`, `CONFIRMED`, or `SUSPENDED` whose half-open residency interval covers the cancelled date — the residency starts on or before the date and ends strictly after it — accrues a daily weather credit into `weather_credit_cents`: one quarter of the assignment's `provisional_fee_cents` divided by the residency's length in whole days, rounded half up to whole cents for that day before being added, per the per-day rounding discipline of §2.7.

### 3.7. Gate Operations: Redemption, Rain Checks, and Voids

At the gate, a `GateAgent` redeems a ticket that must stand `VALID` (else `ERR_TICKET_NOT_VALID`). For a `DAY` ticket, its own faire day must be `OPERATING`; for a `SEASON` pass, some faire day of the season must be `OPERATING` on the clock's current calendar date; either failure is `ERR_DAY_NOT_OPERATING`. Redemption stamps the ticket's `redeemed_at` with the clock instant, moves the ticket to `REDEEMED`, and recomputes the owning order's `redemption_status` per §3.5.

A guest holding an `ISSUED` rain check may redeem it into a future day by naming a `target_faire_day_id`, provided the caller's `X-User-ID` equals the `buyer_email` of the order that sourced the check (else `ERR_NOT_RESOURCE_OWNER`). Four gates guard the exchange, each with its own error: the check must be `ISSUED` (else `ERR_RAIN_CHECK_NOT_ISSUED`); the clock must be on or before the check's `redeem_by_date` (else `ERR_RAIN_CHECK_EXPIRED`); the target day must be `SCHEDULED` or `OPEN_FOR_SALES` (else `ERR_DAY_NOT_REDEEMABLE`); and the target day must have room, its `tickets_sold_count` plus one staying at or below the season's `daily_capacity` (else `ERR_DAY_AT_CAPACITY`). On success the check becomes `REDEEMED`, its `redeemed_on_day_id` records the target day, and a fresh `DAY` ticket in `VALID` status is minted for the target day under the same `order_id` as the source ticket; the season's `outstanding_admissions` is unchanged, one `ISSUED` check consumed against one `VALID` ticket minted. A check never redeemed expires lazily once the clock passes its `redeem_by_date` — becoming `EXPIRED` on its next read or write and decrementing `outstanding_admissions` by one — and any still outstanding are swept when the season closes.

A gate agent may also void a ticket manually while it stands `VALID` (else `ERR_TICKET_NOT_VALID`), moving it to `VOID`, decrementing the season's `outstanding_admissions` by one, and recomputing the owning order's `redemption_status`.

### 3.8. Volunteer Staffing and the Confirmed-Hours Tally

A `Volunteer` signs up for a shift by naming the `season_id`, the `faire_day_id`, a `role` of `GATE`, `PARKING`, `TAVERN`, `INFO`, or `BACKSTAGE`, and a `start_time` and `end_time` with the end strictly later than the start. The server stamps `volunteer_handle` from the caller's `X-User-ID`. The faire day must be `SCHEDULED` or `OPEN_FOR_SALES` — staffing a day already holding, operating, or finished fails with `ERR_DAY_NOT_STAFFABLE` — and the same person may not hold two overlapping live shifts: a new sign-up whose half-open interval intersects that of an existing `SIGNED_UP` or `CONFIRMED` shift under the same `volunteer_handle` is rejected with `ERR_VOLUNTEER_SHIFT_OVERLAP`. The shift's `hours` — the difference between `end_time` and `start_time` in hours — is computed at creation, and the shift stands `SIGNED_UP`.

Confirmation by a `VolunteerCoordinator` moves `SIGNED_UP` → `CONFIRMED` (from any other state, `ERR_SHIFT_NOT_CONFIRMABLE`), adds the shift's `hours` to the season's `volunteer_confirmed_hours`, and re-derives the readiness posture against the season's `volunteer_min_hours`.

Close-out by the coordinator takes an `outcome` against a `CONFIRMED` shift (else `ERR_SHIFT_NOT_CLOSABLE`) and requires the faire day to be `OPERATING` or `COMPLETED` (else `ERR_DAY_NOT_OPERATING`). A `WORKED` outcome leaves the shift's hours counted in the season tally — `WORKED` remains in the confirmed-hours inclusion set of §2.6. A `NO_SHOW` outcome subtracts the shift's `hours` from `volunteer_confirmed_hours` and re-derives the posture.

Cancellation is shared between the volunteer and the coordinator: the caller must either own the shift — `X-User-ID` equal to the shift's `volunteer_handle` — or act as a `VolunteerCoordinator`, else `ERR_NOT_RESOURCE_OWNER`. A shift in `SIGNED_UP` or `CONFIRMED` may be cancelled (else `ERR_SHIFT_NOT_CANCELLABLE`); cancelling a `CONFIRMED` shift subtracts its `hours` from the season tally and re-derives the posture, while cancelling a `SIGNED_UP` shift touches nothing beyond the shift itself. The weather cascade of §3.6 cancels `SIGNED_UP` and `CONFIRMED` shifts automatically when their day is called off.

### 3.9. Conduct Enforcement, Strike, and Season Close

A `GateAgent` files a conduct case with the `season_id`, a `category` of `COSTUME_POLICY`, `WEAPON_UNTIED`, `BEHAVIOR`, or `VENDOR_CONDUCT`, and a free-text `subject_description` of the subject and violation. Two optional linkages frame the sanction the case may later carry: `linked_order_id` naming the ticket order of a guest who might be banned, and `linked_permit_id` naming the permit of a vendor under review — the latter required at filing whenever the `category` is `VENDOR_CONDUCT`. The case opens in `REPORTED` with its `sanction` still `NONE`.

Resolution belongs to the `FaireOperator`, who supplies an `outcome` and, for an upheld case, a `sanction`. The case must still be `REPORTED` — resolving an already-resolved case fails with `ERR_CASE_ALREADY_RESOLVED`. A `DISMISSED` outcome closes the case with no further effect. An `UPHELD` outcome sets the case's `sanction` from the payload and enforces linkage: `BAN_GUEST` requires the case's `linked_order_id` to be present and `REVOKE_PERMIT` requires its `linked_permit_id`, with a missing link rejected as `ERR_CASE_LINKAGE_INVALID`, while `NONE` carries no further effect. An upheld `BAN_GUEST` voids every `VALID` ticket of the linked order, moves the order's `redemption_status` to `VOID` — from `UNREDEEMED` when every ticket is voided together, or from `PARTIALLY_REDEEMED` when the ban voids only the remaining `VALID` tickets and the order carries a mix of `REDEEMED` and `VOID` — and decrements the season's `outstanding_admissions` by one per voided ticket. An upheld `REVOKE_PERMIT` fires the permit cascade of §3.4 in three steps: the linked permit moves `ISSUED` → `REVOKED`, the application's `CONFIRMED` booth drops to `SUSPENDED`, and the season's readiness posture is re-derived.

When the run is over, beginning the strike moves the season `OPEN` → `STRIKE`. The season must be `OPEN` (else `ERR_SEASON_INVALID_STATE`) and every faire day of the season must already stand in a terminal state — `COMPLETED` or `CANCELLED_WEATHER` — else `ERR_UNRESOLVED_FAIRE_DAYS`. The transition settles the season's people and passes: every cast contract in `ACCEPTED`, `REHEARSING`, or `PERFORMING` moves to `COMPLETED` with its `final_payout_cents` computed at the guarantee floor per §3.2, and every `VALID` ticket with `ticket_type` `SEASON` expires to `EXPIRED`, with the season's `outstanding_admissions` recomputed accordingly.

Booth settlement happens during the strike. The coordinator settles any booth in `CONFIRMED` or `SUSPENDED` — from any other state, `ERR_BOOTH_NOT_SETTLEABLE` — and only while the season is in `STRIKE` (else `ERR_SEASON_INVALID_STATE`). The final fee is evaluated in a pinned order: start from the `provisional_fee_cents`, subtract the accumulated `weather_credit_cents` to reach the subtotal, and then, only when the application's `requested_location_tier` is `PRIME` and that post-credit subtotal is at least 20,000 cents, add a surcharge of five percent of the subtotal rounded half up to whole cents — booths under the threshold or in other tiers pay no surcharge. The resulting sum is recorded as `final_fee_cents`, and `settlement_delta_cents` records the difference between the final and provisional fees, a negative value meaning a refund is due to the vendor. The booth then stands `SETTLED`.

Closing the season moves `STRIKE` → `CLOSED` and demands a clean site: the season must be in `STRIKE` (else `ERR_SEASON_INVALID_STATE`), every booth assignment of the season must stand `SETTLED` or `RELEASED` (else `ERR_UNSETTLED_BOOTHS`), and every build task with `phase` `STRIKE` must be `DONE` (else `ERR_STRIKE_TASKS_INCOMPLETE`). The close sweeps the last open obligation: every rain check still `ISSUED` whose `redeem_by_date` has passed expires to `EXPIRED`, decrementing the season's `outstanding_admissions` by one per expired check.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that modify an existing resource, drive a state transition, or read data return a `200 OK` status code. The list endpoints accept the optional filters referenced throughout §3 — among them `season_id`, `status`, `performer_id`, `contract_id`, `stage_name`, `category`, `vendor_id`, `application_id`, `booth_site`, `faire_day_id`, `buyer_email`, `payment_status`, `order_id`, `ticket_id`, `issued_for_day_id`, `redeemed_on_day_id`, `volunteer_handle`, `linked_order_id`, `linked_permit_id`, `phase`, and `depends_on_task_ids` — alongside the `limit` and `offset` pagination parameters of §2.3. The table below is a routing summary only; request fields, preconditions, and side effects are defined by the narratives above.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/seasons` | Create a season | FaireOperator |
| GET | `/seasons` | List seasons | Any |
| GET | `/seasons/{id}` | Get a season | Any |
| PATCH | `/seasons/{id}` | Edit a PLANNING season's configuration | FaireOperator |
| POST | `/seasons/{id}/begin-build` | Move a season from PLANNING to BUILD | FaireOperator |
| POST | `/seasons/{id}/open` | Open a READY season | FaireOperator |
| POST | `/seasons/{id}/begin-strike` | Move an OPEN season to STRIKE | FaireOperator |
| POST | `/seasons/{id}/close` | Close a STRIKE season | FaireOperator |
| POST | `/faire-days` | Schedule a faire day | FaireOperator |
| GET | `/faire-days` | List faire days | Any |
| GET | `/faire-days/{id}` | Get a faire day | Any |
| POST | `/faire-days/{id}/open-sales` | Open ticket sales for a day | FaireOperator |
| POST | `/faire-days/{id}/weather-hold` | Place a day on weather hold | FaireOperator |
| POST | `/faire-days/{id}/release-hold` | Release a day from weather hold | FaireOperator |
| POST | `/faire-days/{id}/cancel-weather` | Weather-cancel a faire day | FaireOperator |
| POST | `/faire-days/{id}/open-gates` | Begin operating a faire day | FaireOperator |
| POST | `/faire-days/{id}/complete` | Complete an operating day | FaireOperator |
| POST | `/performers` | Register a performer | CastDirector |
| GET | `/performers` | List performers | Any |
| GET | `/performers/{id}` | Get a performer | Any |
| POST | `/cast-contracts` | Create a cast contract | CastDirector |
| GET | `/cast-contracts` | List cast contracts | Any |
| GET | `/cast-contracts/{id}` | Get a cast contract | Any |
| POST | `/cast-contracts/{id}/offer` | Offer or re-offer contract terms | CastDirector |
| POST | `/cast-contracts/{id}/counter` | Counter the current offer | Performer |
| POST | `/cast-contracts/{id}/accept` | Accept the current offer | Performer |
| POST | `/cast-contracts/{id}/terminate` | Terminate a cast contract | CastDirector |
| POST | `/rehearsal-slots` | Schedule a rehearsal slot | CastDirector |
| GET | `/rehearsal-slots` | List rehearsal slots | Any |
| GET | `/rehearsal-slots/{id}` | Get a rehearsal slot | Any |
| POST | `/rehearsal-slots/{id}/record-attendance` | Record a slot's attendance outcome | CastDirector |
| POST | `/rehearsal-slots/{id}/cancel` | Cancel a rehearsal slot | CastDirector |
| POST | `/vendors` | Register a vendor | VendorCoordinator |
| GET | `/vendors` | List vendors | Any |
| GET | `/vendors/{id}` | Get a vendor | Any |
| POST | `/vendor-applications` | File a jury application | Vendor |
| GET | `/vendor-applications` | List vendor applications | Any |
| GET | `/vendor-applications/{id}` | Get a vendor application | Any |
| POST | `/vendor-applications/{id}/decide` | Record jury scores and decision | VendorCoordinator |
| POST | `/vendor-applications/{id}/appeal` | Appeal a JURIED_OUT decision | Vendor |
| POST | `/vendor-applications/{id}/withdraw` | Withdraw an application | Vendor |
| POST | `/booth-assignments` | Reserve a booth for a JURIED_IN application | VendorCoordinator |
| GET | `/booth-assignments` | List booth assignments | Any |
| GET | `/booth-assignments/{id}` | Get a booth assignment | Any |
| POST | `/booth-assignments/{id}/confirm` | Confirm a booth reservation | Vendor |
| POST | `/booth-assignments/{id}/release` | Release a reservation and promote the waitlist | VendorCoordinator |
| POST | `/booth-assignments/{id}/settle` | Settle a booth's final fee | VendorCoordinator |
| POST | `/food-permits` | Apply for a health permit | Vendor |
| GET | `/food-permits` | List food permits | Any |
| GET | `/food-permits/{id}` | Get a food permit | Any |
| POST | `/food-permits/{id}/inspect` | Record an inspection outcome | VendorCoordinator |
| POST | `/food-permits/{id}/revoke` | Revoke an issued permit | VendorCoordinator |
| POST | `/ticket-orders` | Create a ticket order | Guest |
| GET | `/ticket-orders` | List ticket orders | Any |
| GET | `/ticket-orders/{id}` | Get a ticket order | Any |
| PATCH | `/ticket-orders/{id}` | Edit an unpaid ticket order | Guest |
| POST | `/ticket-orders/{id}/pay` | Pay an order and mint its tickets | Guest |
| POST | `/ticket-orders/{id}/refund` | Refund an order fully or partially | GateAgent |
| GET | `/tickets` | List tickets | Any |
| GET | `/tickets/{id}` | Get a ticket | Any |
| POST | `/tickets/{id}/redeem` | Redeem a ticket at the gate | GateAgent |
| POST | `/tickets/{id}/void` | Void a ticket manually | GateAgent |
| GET | `/rain-checks` | List rain checks | Any |
| GET | `/rain-checks/{id}` | Get a rain check | Any |
| POST | `/rain-checks/{id}/redeem` | Redeem a rain check into a new day ticket | Guest |
| POST | `/volunteer-shifts` | Sign up for a volunteer shift | Volunteer |
| GET | `/volunteer-shifts` | List volunteer shifts | Any |
| GET | `/volunteer-shifts/{id}` | Get a volunteer shift | Any |
| POST | `/volunteer-shifts/{id}/confirm` | Confirm a signed-up shift | VolunteerCoordinator |
| POST | `/volunteer-shifts/{id}/close-out` | Close out a confirmed shift | VolunteerCoordinator |
| POST | `/volunteer-shifts/{id}/cancel` | Cancel a shift | Volunteer, VolunteerCoordinator |
| POST | `/conduct-cases` | File a conduct case | GateAgent |
| GET | `/conduct-cases` | List conduct cases | Any |
| GET | `/conduct-cases/{id}` | Get a conduct case | Any |
| POST | `/conduct-cases/{id}/resolve` | Resolve a conduct case | FaireOperator |
| POST | `/build-tasks` | Create a build or strike task | FaireOperator |
| GET | `/build-tasks` | List build tasks | Any |
| GET | `/build-tasks/{id}` | Get a build task | Any |
| GET | `/build-tasks/{id}/dependents` | List tasks depending on this task | Any |
| POST | `/build-tasks/{id}/dependencies` | Add dependencies to a task | FaireOperator |
| POST | `/build-tasks/{id}/advance` | Advance a task's status | FaireOperator |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | FaireOperator |

## 5. Error Code Catalogue

Trigger conditions for each error are defined by the narratives in §2 and §3; this table is the identifier-to-status mapping only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SEASON_NOT_FOUND` | 404 Not Found |
| `ERR_FAIRE_DAY_NOT_FOUND` | 404 Not Found |
| `ERR_PERFORMER_NOT_FOUND` | 404 Not Found |
| `ERR_CONTRACT_NOT_FOUND` | 404 Not Found |
| `ERR_SLOT_NOT_FOUND` | 404 Not Found |
| `ERR_VENDOR_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_BOOTH_NOT_FOUND` | 404 Not Found |
| `ERR_PERMIT_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_TICKET_NOT_FOUND` | 404 Not Found |
| `ERR_RAIN_CHECK_NOT_FOUND` | 404 Not Found |
| `ERR_SHIFT_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_TASK_NOT_FOUND` | 404 Not Found |
| `ERR_SEASON_NOT_IN_PLANNING` | 409 Conflict |
| `ERR_SEASON_INVALID_STATE` | 409 Conflict |
| `ERR_SEASON_NOT_READY` | 409 Conflict |
| `ERR_SEASON_POSTURE_BLOCKED` | 409 Conflict |
| `ERR_SEASON_NOT_OPEN` | 409 Conflict |
| `ERR_UNRESOLVED_FAIRE_DAYS` | 409 Conflict |
| `ERR_STRIKE_TASKS_INCOMPLETE` | 409 Conflict |
| `ERR_UNSETTLED_BOOTHS` | 409 Conflict |
| `ERR_DAY_NOT_OPENABLE` | 409 Conflict |
| `ERR_DAY_NOT_HOLDABLE` | 409 Conflict |
| `ERR_DAY_NOT_ON_HOLD` | 409 Conflict |
| `ERR_DAY_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_DAY_NOT_COMPLETABLE` | 409 Conflict |
| `ERR_OPEN_SHIFTS_EXIST` | 409 Conflict |
| `ERR_WEATHER_CALL_TOO_LATE` | 409 Conflict |
| `ERR_DAY_NOT_TODAY` | 409 Conflict |
| `ERR_DAY_NOT_OPERATING` | 409 Conflict |
| `ERR_DAY_NOT_REDEEMABLE` | 409 Conflict |
| `ERR_DAY_NOT_STAFFABLE` | 409 Conflict |
| `ERR_CONTRACT_NOT_OFFERABLE` | 409 Conflict |
| `ERR_CONTRACT_NOT_OFFERED` | 409 Conflict |
| `ERR_CONTRACT_NOT_TERMINABLE` | 409 Conflict |
| `ERR_CONTRACT_NOT_REHEARSABLE` | 409 Conflict |
| `ERR_SLOT_NOT_RECORDABLE` | 409 Conflict |
| `ERR_SLOT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_REHEARSAL_OVERLAP` | 409 Conflict |
| `ERR_DUPLICATE_APPLICATION` | 409 Conflict |
| `ERR_APPLICATION_NOT_DECIDABLE` | 409 Conflict |
| `ERR_APPLICATION_NOT_APPEALABLE` | 409 Conflict |
| `ERR_APPEAL_ALREADY_USED` | 409 Conflict |
| `ERR_APPLICATION_NOT_WITHDRAWABLE` | 409 Conflict |
| `ERR_APPLICATION_NOT_JURIED_IN` | 409 Conflict |
| `ERR_APPLICATION_ALREADY_BOOKED` | 409 Conflict |
| `ERR_BOOTH_OVERLAP` | 409 Conflict |
| `ERR_BOOTH_NOT_CONFIRMABLE` | 409 Conflict |
| `ERR_BOOTH_NOT_RELEASEABLE` | 409 Conflict |
| `ERR_BOOTH_NOT_SETTLEABLE` | 409 Conflict |
| `ERR_FOOD_PERMIT_NOT_ISSUED` | 409 Conflict |
| `ERR_PERMIT_NOT_APPLICABLE` | 409 Conflict |
| `ERR_DUPLICATE_PERMIT` | 409 Conflict |
| `ERR_PERMIT_NOT_INSPECTIONABLE` | 409 Conflict |
| `ERR_PERMIT_NOT_REVOKABLE` | 409 Conflict |
| `ERR_GROUP_SIZE_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `ERR_DAY_AT_CAPACITY` | 409 Conflict |
| `ERR_ORDER_NOT_UNPAID` | 409 Conflict |
| `ERR_REFUND_EXCEEDS_PAID` | 422 Unprocessable Entity |
| `ERR_NOTHING_REFUNDABLE` | 409 Conflict |
| `ERR_ORDER_NOT_REFUNDABLE` | 409 Conflict |
| `ERR_TICKET_NOT_VALID` | 409 Conflict |
| `ERR_RAIN_CHECK_NOT_ISSUED` | 409 Conflict |
| `ERR_RAIN_CHECK_EXPIRED` | 409 Conflict |
| `ERR_VOLUNTEER_SHIFT_OVERLAP` | 409 Conflict |
| `ERR_SHIFT_NOT_CONFIRMABLE` | 409 Conflict |
| `ERR_SHIFT_NOT_CLOSABLE` | 409 Conflict |
| `ERR_SHIFT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_CASE_ALREADY_RESOLVED` | 409 Conflict |
| `ERR_CASE_LINKAGE_INVALID` | 409 Conflict |
| `ERR_TASK_DEPENDENCY_UNMET` | 409 Conflict |
| `ERR_TASK_DEPENDENCY_CYCLE` | 409 Conflict |
| `ERR_TASK_NOT_ADVANCEABLE` | 409 Conflict |

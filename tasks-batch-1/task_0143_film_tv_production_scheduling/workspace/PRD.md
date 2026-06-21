# Film TV Production Scheduling API — Product Requirements Document

## 1. Introduction

Producing a film or television project means running several tightly coupled clocks at once: a stripboard of shooting days that must each be called, shot, and wrapped on schedule; a payroll obligation that swells with every union meal missed and every forced early call; a portfolio of municipal permits whose occupation windows cannot be allowed to collide; and a post-production review queue that decides which footage is keepable and which must be reshot. This API exists to give a production office a single authoritative system of record that keeps all of those clocks consistent with one another.

The platform is organized around a **Production** — a feature film or an episodic show — and the satellite records that hang off it: budget lines, the shooting schedule and its scenes, the crew and cast hired onto it, the daily assignments that book a person onto a day, the call sheets that summon everyone to set, the locations and their permits, the residual obligations the finished work later generates, and the union fringe configuration that governs labor cost. Four operational owners share the workload — a line producer who controls the money and the legal/location apparatus, a first assistant director who runs the floor and the schedule, a payroll coordinator who closes out pay and tracks residuals, and a post supervisor who shepherds dailies — while a union representative observes everything in a read-only audit capacity. The sections below specify the system-wide contract every endpoint honors (Section 2) and then the domain workflows that the contract serves (Section 3), with the concrete endpoint and error inventories collected at the end (Sections 4 and 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are valid but the named role is not permitted to perform the requested operation under the access matrix, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly five roles: `LineProducer`, `FirstAD`, `PayrollCoordinator`, `PostSupervisor`, and `UnionRep`. The `LineProducer` owns the production shell itself, the budget, crew and cast hiring, locations, permits, and the union fringe configuration. The `FirstAD` — the first assistant director — owns the shooting schedule: shooting days, scenes, crew assignments, and call sheets. The `PayrollCoordinator` owns the pay side of an assignment (approval and payment) together with residual recording. The `PostSupervisor` owns the dailies review pipeline. The `UnionRep` is a read-only audit role for union compliance and holds no mutating capability of any kind.

For all five roles, `X-User-Role` carries an opaque operator identifier. `X-User-ID` in every case is an opaque operator identifier that is not tied to any persisted entity; the server may record or log it, but it never compares `X-User-ID` to any entity's `id` when deciding ownership. Authorization is therefore decided purely by role, not by matching the caller's identity to a particular production, assignment, or other record.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items a single page returns; when omitted it defaults to 10, and a supplied value must lie between a minimum of 1 and a maximum of 100. The `offset` parameter is the count of items to skip before the page begins; when omitted it defaults to 0, and any supplied value must be at least 0. A `limit` outside the 1-to-100 band, or a negative `offset`, is rejected with `ERR_PAGINATION_INVALID`.

Unless an endpoint explicitly states otherwise, every list is returned sorted by the resources' creation timestamp in ascending order. Each list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Versioning Contract

Most resources in the system carry a uniform set of system-managed fields. The `id` is a server-minted UUID assigned at creation; it carries no type prefix and is never supplied by the client. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits stamped once at creation. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation of the resource. The `version` field is an integer that begins at 1 when the resource is created and increases by exactly 1 on each subsequent mutation; it is the basis for the optimistic concurrency mechanism described in Section 2.6.

One entity is deliberately leaner. A residual event is an immutable accounting fact once recorded: it carries only an `id` and a `created_at`, and it has neither an `updated_at` field nor a `version` field. No other entity omits these fields.

When a derived or computed field on a resource changes — for instance, when a production's rolled-up cost figures are recomputed — that recomputation is itself a mutation: it refreshes `updated_at` and increments `version` on the resource whose field changed.

### 2.5. Hierarchical Consistency and Cascading Effects

The records in this system form a hierarchy rooted at the production. Several operations on a parent resource therefore reach down and mutate children, and each such cascade independently bumps the affected child's `version` and refreshes its `updated_at`. The most consequential cascade is the cancellation of a shooting day, which simultaneously voids the people booked on it, releases the scenes scheduled onto it, and (in one branch) cancels the day's published call sheet; the full mechanics are spelled out in the schedule workflow. Payroll settlement is likewise a cascade: marking an assignment paid moves money onto the production and onto two specific budget lines at once. Whenever the specification says one action changes more than one record, every one of those changes occurs as part of that single action.

For requests that name a resource by its identifier in the path, the system validates existence first and left-to-right: the path identifier is resolved before any foreign-key reference in the body, and any referenced resource that does not exist yields `ERR_NOT_FOUND` against the first missing reference encountered. Because the URL space is flat — every collection is addressed at the top level and parent references travel in the request body rather than in the path — this left-to-right rule governs the path identifier first and then each body foreign key in the order the operation consumes them.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded against acting on a stale view of their parent, and both express the guard through a mandatory version field in the request body.

Booking a crew member onto a shooting day requires `expected_shooting_day_version`, which must carry the version of the target shooting day that the client last observed. A prior writer may have cancelled or wrapped that day — advancing its `version` and changing which bookings are even legal — so if the supplied `expected_shooting_day_version` does not equal the day's current `version`, the booking is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than layered onto a day the client has not actually seen in its present form.

Posting a manual actual to a budget line requires `expected_production_version`, which must carry the version of the owning production that the client last observed. When another writer has already mutated that production — for example, a payment-settlement cascade that bumped the production's cost figures and its `version` — a posting whose `expected_production_version` no longer equals the production's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), so the actual is never stacked on top of an unobserved cost change.

These are the only two endpoints that take a version field. No other operation accepts or requires an `expected_*_version` input.

### 2.7. Monetary Precision and Rounding

All monetary quantities are stored and returned as whole integer cents; there are no fractional-cent values anywhere in the system. Where a calculation multiplies by a rate — a fringe basis-point rate or an overtime multiplier — the multiplication is carried out and then rounded to the nearest whole cent using the round-half-up convention (a value exactly halfway between two cents rounds up). The specific rounding boundaries for each calculation (which term is rounded, and whether rounding happens before or after a flat addend) are stated alongside each calculation in Section 3; they matter, and they are not interchangeable.

### 2.8. The Order of Validation

When an operation can fail several checks, the checks are applied in a fixed precedence so that the returned error is deterministic. Authentication is evaluated first: a request lacking valid headers or naming an unknown role fails with `ERR_UNAUTHENTICATED`. Authorization is second: a known role attempting an operation it is not permitted to perform fails with `ERR_FORBIDDEN`. Existence is third: any path or foreign-key resource that does not exist fails with `ERR_NOT_FOUND`, evaluated left-to-right. Request well-formedness is fourth: a missing required field, a wrong type, or an enum value outside its declared set fails with `ERR_INVALID_REQUEST`, and a numeric field that is present and correctly typed but outside its declared range fails with `ERR_VALIDATION_FAILED`; pagination-bound violations on list endpoints surface as `ERR_PAGINATION_INVALID`. For an operation that drives a state machine, the system fifth confirms the target resource is in a state from which the requested transition is defined, failing otherwise with `ERR_INVALID_STATE`. Sixth, where an operation is OCC-guarded, the version check from Section 2.6 runs and a mismatch fails with `ERR_STALE_VERSION`. Only after all of these pass does the system evaluate the domain-specific business rules described in Section 3 (cross-production references, double bookings, window conflicts, budget ceilings, and so on). In short: authentication, then authorization, then existence, then request validity, then state, then concurrency, then business rules.

## 3. Business Logic & Workflows

### 3.1. The Production Lifecycle

Everything begins when a `LineProducer` opens a **production** by supplying its `title`, its `production_type` — either `FEATURE` for a feature film or `EPISODIC` for episodic television — and an approved top-line `total_budget_cents`, which must be zero or greater. A freshly created production lands with its `status` field set to `DRAFT`, and its three rolled-up money figures — `committed_cost_cents`, `actual_cost_cents`, and `residual_reserve_cents` — all initialized to zero. The lifecycle then advances one step at a time through `DRAFT`, `PRE_PRODUCTION`, `ACTIVE`, and `WRAPPED`, and finally to the terminal `CLOSED`. Each forward step is requested by the `LineProducer`.

Advancing from `DRAFT` to `PRE_PRODUCTION` is permitted only while the production is in `DRAFT` and only once at least one budget line exists for it; the advance increments the production's `version`. Advancing from `PRE_PRODUCTION` to `ACTIVE` requires the production to currently be in `PRE_PRODUCTION` and at least one shooting day to exist for it, and again increments `version`. Advancing from `ACTIVE` to `WRAPPED` requires the production to be in `ACTIVE` and, critically, that none of its shooting days remain in `PLANNED`, `CALLED`, or `IN_PROGRESS` — every day must already have reached `WRAPPED` or `CANCELLED` — and it increments `version`. Any advance attempted from a state that does not match the expected source state is refused with `ERR_INVALID_STATE`.

Closing a production is a separate action, distinct from the stepwise advance, and moves it from `WRAPPED` to `CLOSED`. It is permitted only while the production is `WRAPPED` and only when no assignment of the production is still financially open — that is, no assignment has a `payment_status` of `UNPAID` or `APPROVED`. Closing increments `version`. A close requested from any state other than `WRAPPED` is refused with `ERR_INVALID_STATE`. `CLOSED` is terminal.

A separate budget-summary capability rolls up the production's finances on demand for a `LineProducer`, `PayrollCoordinator`, or `UnionRep`. It returns `total_estimated_cents` (the sum of `estimated_cents` across all of the production's budget lines), `total_actual_cents` (the sum of `actual_cents` across those same lines), `total_variance_cents` (the total estimated minus the total actual), `over_budget` (true only when total actual is strictly greater than total estimated — a production whose actual exactly equals its estimate is not over budget), and `residual_reserve_cents` (the production's accrued residual liability). Each individual budget line's own `variance_cents` is its `estimated_cents` minus its `actual_cents`, where a positive value means the line is under budget.

### 3.2. Budget Lines and Manual Actuals

A `LineProducer` populates the budget by creating **budget lines** under a production, each addressed to that production via `production_id` and tagged with a `category` drawn from `ABOVE_THE_LINE`, `BELOW_THE_LINE_LABOR`, `LOCATIONS`, `POST`, or `FRINGES`. Each line is created with an `estimated_cents` figure of zero or greater; on creation its `actual_cents` starts at zero and its `variance_cents` therefore equals the estimate. The `actual_cents` figure accumulates real spend over time. For the `BELOW_THE_LINE_LABOR` line it is fed automatically by payroll settlement, for the `FRINGES` line it is fed automatically by accrued fringe, and for every other category it advances only through explicit manual postings.

A manual posting adds an `amount_cents` to a chosen budget line's `actual_cents` and recomputes that line's `variance_cents`; it also increments the owning production's `version`. Because the posting reads and writes against the production's running cost picture, it is OCC-guarded: the request carries `expected_production_version`, and a mismatch against the production's current `version` is rejected with `ERR_STALE_VERSION` exactly as described in Section 2.6. Only a `LineProducer` may post an actual.

### 3.3. Building the Stripboard: Shooting Days and Scenes

The `FirstAD` lays out the shooting schedule as a sequence of **shooting days**. Creating a day takes the `production_id`, the calendar `shoot_date` in `YYYY-MM-DD` form, a stripboard `day_number` that must be at least 1, and an optional `unit` naming which crew is covering — one of `MAIN`, `SECOND`, or `SPLINTER`, defaulting to `MAIN` when omitted. A new day opens in `PLANNED`. The `day_number` must be unique among the production's days that have not been cancelled: if another non-`CANCELLED` shooting day of the same production already carries that number, the create is refused with `ERR_DUPLICATE_DAY_NUMBER`. A day also tracks an `estimated_page_eighths` figure, which is the sum of the page lengths of all scenes currently scheduled onto it and starts at zero.

A **scene** is a strip from the script. The `FirstAD` creates one with its `production_id`, a `scene_number` such as "14A", a `page_eighths` length measured in eighths of a page that must be at least 1, an `int_ext` value of either `INT` or `EXT`, and a `day_night` value of either `DAY` or `NIGHT`. A scene is created unscheduled — its `shooting_day_id` is null — and scheduling it onto a day is a separate action. That scheduling action supplies the target `shooting_day_id` and is permitted only when the target day belongs to the same production as the scene and is currently in `PLANNED`; if the day is not `PLANNED` or belongs to a different production, the request is refused with `ERR_SCENE_SCHEDULE_LOCKED`. A successful scheduling sets the scene's `shooting_day_id` and recomputes the parent day's `estimated_page_eighths`.

Once a day has at least one assignment on it and the production is `ACTIVE`, the day can be **called** by publishing its call sheet (see Section 3.6), which moves the day from `PLANNED` to `CALLED`. From `CALLED` the `FirstAD` **starts** the day, taking it to `IN_PROGRESS`; a start is permitted only from `CALLED` and increments the day's `version`. The `FirstAD` later **wraps** an `IN_PROGRESS` day to `WRAPPED`, incrementing `version` — but a wrap is allowed only when no assignment on that day is still open, meaning none has an `attendance_status` of `SCHEDULED` or `CHECKED_IN`; an attempt to wrap a day with open assignments is refused with `ERR_OPEN_ASSIGNMENTS_BLOCK_WRAP`. Both `WRAPPED` and `CANCELLED` are terminal day states.

Cancelling a day is the system's most far-reaching schedule action and is available to the `FirstAD` while the day is either `PLANNED` or `CALLED`. In both cases the cancellation moves the day to `CANCELLED`, increments the day's `version`, forces every assignment on the day whose `attendance_status` is `SCHEDULED` into `NO_SHOW` while setting that assignment's `payment_status` to `VOID`, and unschedules every scene scheduled on the day by resetting each scene's `shooting_day_id` to null. The two branches differ in exactly one respect: when the cancelled day was already `CALLED`, the day's published call sheet is additionally transitioned from `PUBLISHED` to `CANCELLED`; when the day was merely `PLANNED`, there is no published call sheet to cancel and that step does not occur.

### 3.4. Hiring Crew and Booking Assignments

A `LineProducer` hires each person — cast or crew — onto a production as a **crew member**, supplying the `production_id`, the person's `full_name`, their `role_title` such as "Lead Actor" or "Gaffer", and their contracted `daily_rate_cents` (zero or greater). Two further inputs govern how that person's labor is costed: `is_sag_aftra`, a boolean defaulting to false that marks the person as covered by the SAG-AFTRA agreement, and `union_code`, one of `SAG_AFTRA`, `IATSE`, `DGA`, or `NONE` (defaulting to `NONE`), naming the union local whose fringe rules apply.

The `FirstAD` books a person onto a day by creating an **assignment**, which references the day via `shooting_day_id`, the person via `crew_member_id`, and carries the scheduled `call_time` as an ISO 8601 UTC instant plus the OCC field `expected_shooting_day_version` described in Section 2.6. Two referential guards apply at booking. First, the referenced crew member and the referenced shooting day must belong to the same production; a cross-reference between productions is refused with `ERR_CROSS_PRODUCTION_REFERENCE`. Second, a person may hold only one booking per day: if the crew member already has an assignment on that shooting day, the create is refused with `ERR_DOUBLE_BOOKED`. A new assignment opens with `attendance_status` of `SCHEDULED` and `payment_status` of `UNPAID`. Creating it computes a forward-looking `estimated_cost_cents` (detailed in Section 3.5), recomputes the production's `committed_cost_cents`, and increments the shooting day's `version`.

An assignment carries two independent state dimensions that are advanced by different actors. The **attendance** dimension runs `SCHEDULED` → `CHECKED_IN` → `WRAPPED`, with `SCHEDULED` → `NO_SHOW` as the alternate terminal path; the **payment** dimension runs `UNPAID` → `APPROVED` → `PAID`, with `VOID` as the alternate terminal. The `FirstAD` drives attendance; the `PayrollCoordinator` drives payment.

Checking a person in moves attendance from `SCHEDULED` to `CHECKED_IN` and increments the assignment's `version`; it is permitted only when the assignment is `SCHEDULED` and the parent day is `IN_PROGRESS`. Marking a no-show moves attendance from `SCHEDULED` to `NO_SHOW`, forces `payment_status` to `VOID`, and increments `version`; it is permitted only while the assignment is `SCHEDULED`. (The same `SCHEDULED` → `NO_SHOW` / payment-to-`VOID` outcome is what the day-cancellation cascade in Section 3.3 produces automatically.) Each of these state moves, attempted from the wrong source state, is refused with `ERR_INVALID_STATE`.

Checking a person out is the richest attendance step: it moves attendance from `CHECKED_IN` to `WRAPPED` and is permitted only when the assignment is `CHECKED_IN`. The request supplies the actual `wrap_time` as an ISO 8601 UTC instant and an optional `meal_breaks_taken` count (a non-negative integer defaulting to 0). The `wrap_time` must be strictly later than the assignment's `call_time`; if it is not, the check-out is refused with `ERR_INVALID_TIME_RANGE`. A successful check-out stamps `wrap_time`, computes `hours_worked` as the elapsed time from `call_time` to `wrap_time` expressed in hours, resolves the person's `prior_assignment_id`, computes `meal_penalty_cents`, `turnaround_penalty_cents`, and `fringe_cents` (all detailed in Section 3.5), and increments `version`. Resolving `prior_assignment_id` means finding the same crew member's most recent already-`WRAPPED` assignment ordered by `wrap_time` descending, breaking ties by `created_at` descending, and recording its `id`; if the person has no prior wrapped assignment, `prior_assignment_id` is null. One further temporal guard fires at check-out: the same crew member's wrapped occupations may not collide. Treating each wrapped assignment's `[call_time, wrap_time]` as a closed interval — so two intervals that merely touch at an endpoint still conflict — if this check-out would overlap another wrapped assignment of the same person, it is refused with `ERR_CREW_TIME_CONFLICT`.

### 3.5. Costing Labor: Estimates, Penalties, Fringe, and Final Pay

The system computes an assignment's cost twice over its life, and the two figures deliberately diverge whenever reality departs from the booking-time plan.

**At booking**, the forward-looking `estimated_cost_cents` is the sum of a base and a projected fringe. The base is the crew member's contracted `daily_rate_cents`. The projected fringe is computed only when the person's `union_code` is one of `SAG_AFTRA`, `IATSE`, or `DGA` *and* the production has a matching union fringe configuration for that code; in that case the projected fringe is the base multiplied by that configuration's `fringe_rate_bps`, divided by 10000, rounded half-up to whole cents, and then with the configuration's `pension_health_flat_cents` added on top of the rounded figure. If the person's `union_code` is `NONE`, or no matching fringe configuration exists, the projected fringe is zero. No meal, turnaround, or overtime amounts are projected at booking — the estimate reflects only the contracted day rate and the projected fringe.

**At check-out**, three accruals are stamped. The first is the **meal penalty**, which applies only to crew where `is_sag_aftra` is true — for anyone whose `is_sag_aftra` is false the meal penalty is zero regardless of the hours worked. For SAG-AFTRA crew, a meal must be called within every six worked hours, so the number of required meals is the worked hours divided by six and rounded down to a whole number; the number of missed meals is that required count minus the `meal_breaks_taken` reported at check-out, but never below zero. If no meals were missed the penalty is zero; otherwise the penalty is 2500 cents for the first missed meal plus 3500 cents for each additional missed meal beyond the first. (The boundary is inclusive at six hours: reaching exactly six worked hours triggers the first required meal.)

The second accrual is the **turnaround penalty**, which protects rest between consecutive bookings of the same person. It is zero whenever the assignment has no resolved `prior_assignment_id` or the crew member's `is_sag_aftra` is false. When a prior wrapped assignment does exist and the person is SAG-AFTRA, the rest is the elapsed time from the prior assignment's `wrap_time` to this assignment's `call_time` expressed in hours; if that rest is at least ten hours the turnaround penalty is zero, and if it is strictly under ten hours the breach incurs a flat forced-call penalty of exactly one full `daily_rate_cents`.

The third accrual is the **union fringe**, stamped into `fringe_cents`. It is computed only when the person's `union_code` is one of `SAG_AFTRA`, `IATSE`, or `DGA` and the production has a matching fringe configuration for that code; then it is the `daily_rate_cents` multiplied by the configuration's `fringe_rate_bps`, divided by 10000, rounded half-up to whole cents, with `pension_health_flat_cents` added on top of the rounded figure (round first, then add the flat term). Absent a qualifying union code or a matching configuration, the fringe is zero.

**At pay approval**, the `PayrollCoordinator` approves a wrapped assignment for payment, moving `payment_status` from `UNPAID` to `APPROVED`; this is permitted only while `payment_status` is `UNPAID` and the assignment's `attendance_status` is `WRAPPED`. Approval locks the final actual cost into `paid_cost_cents` and recomputes the production's `committed_cost_cents`, and increments the assignment's `version`. The locked `paid_cost_cents` is the sum of five terms: straight time, equal to the `daily_rate_cents`; overtime; the stamped `meal_penalty_cents`; the stamped `turnaround_penalty_cents`; and the stamped `fringe_cents`. Overtime covers hours worked beyond a standard twelve-hour day: the overtime hours are the worked hours minus twelve but never below zero, the hourly equivalent of the day rate is the `daily_rate_cents` divided by twelve, and the overtime amount is that hourly equivalent multiplied by an overtime multiplier of one-and-one-half and then by the overtime hours, with the whole product rounded half-up to whole cents as a single term (the multiplication is performed in full and rounded once, not rounded per hour). Approval is also the production's budget gate: if locking this `paid_cost_cents` would push the production's `committed_cost_cents` strictly above its `total_budget_cents`, the approval is refused with `ERR_BUDGET_WOULD_EXCEED` (a result that exactly equals the budget is allowed).

**At payment**, the `PayrollCoordinator` marks an `APPROVED` assignment as `PAID`; this is permitted only while `payment_status` is `APPROVED` and increments the assignment's `version`. Marking paid settles the money: the production's `actual_cost_cents` is increased by the assignment's `paid_cost_cents`; the production's `BELOW_THE_LINE_LABOR` budget line has its `actual_cents` increased by the `paid_cost_cents` less the `fringe_cents` (the labor portion), with that line's `variance_cents` recomputed; and the production's `FRINGES` budget line has its `actual_cents` increased by the `fringe_cents`, with its `variance_cents` recomputed. The production's `committed_cost_cents` is the running sum, across all of the production's assignments, of `estimated_cost_cents` for assignments whose `payment_status` is `UNPAID` or `APPROVED` plus `paid_cost_cents` for assignments whose `payment_status` is `PAID`, recomputed whenever an assignment's cost changes; its `actual_cost_cents` is the sum of `paid_cost_cents` across only the `PAID` assignments.

### 3.6. Call Sheets and Calling the Day

A call sheet is the document that formally summons everyone to set. The `FirstAD` creates a **call sheet** for a day by supplying the `shooting_day_id` and the `general_call_time` (an ISO 8601 UTC instant printed as the general crew call). A new sheet opens in `DRAFT` with a `revision_number` of 0 and a null `published_at`.

**Publishing** a `DRAFT` sheet is the act that calls the day. It is permitted only when the sheet is `DRAFT`, its parent shooting day is `PLANNED`, that day has at least one assignment, and the grandparent production is `ACTIVE`; if the production is not `ACTIVE`, publication is refused with `ERR_PRODUCTION_NOT_ACTIVE`, and a sheet not in a publishable state is refused with `ERR_INVALID_STATE`. A successful first publish moves the sheet from `DRAFT` to `PUBLISHED`, stamps `published_at`, increments the sheet's `version`, and transitions the parent day from `PLANNED` to `CALLED`.

A `PUBLISHED` sheet can be **revised** by the `FirstAD` while the parent day is in `CALLED` or `IN_PROGRESS`; revision moves the sheet from `PUBLISHED` to `REVISED`, increases its `revision_number` by 1, and increments its `version`. A `REVISED` sheet is then **re-published** back to `PUBLISHED`, which re-stamps `published_at` and increments `version`; unlike the first publish this re-publish neither calls the day nor requires the day to be `PLANNED` (the day has long since been called). This revise-then-republish loop may repeat any number of times. A `PUBLISHED` sheet is **finalized** by the `FirstAD` once the parent day has reached `WRAPPED`, moving the sheet from `PUBLISHED` to `FINALIZED` and incrementing `version`. Separately, when a `CALLED` day is cancelled, the system cascades its `PUBLISHED` sheet to `CANCELLED` (incrementing the sheet's `version`) as described in Section 3.3. Both `FINALIZED` and `CANCELLED` are terminal call-sheet states; any of these call-sheet transitions attempted from a non-matching source state is refused with `ERR_INVALID_STATE`.

### 3.7. Locations, Permits, and Window Conflicts

A `LineProducer` registers a **location** under a production with its `production_id`, a `name`, and a physical `address`. Against a location the producer then requests a **permit**, supplying the `location_id`, the municipal `permit_number`, and the occupation window as a `window_start` (inclusive) and `window_end` (exclusive), both ISO 8601 UTC instants. The `window_end` must be strictly after `window_start`; if it is not, the create is refused with `ERR_INVALID_TIME_RANGE`. A new permit opens in `REQUESTED`.

A permit moves through its lifecycle entirely under the `LineProducer`. **Approving** a `REQUESTED` permit takes it to `APPROVED`, but only if no other already-`APPROVED` or `ACTIVE` permit on the same location overlaps this permit's window; overlap is judged on the half-open interval `[window_start, window_end)`, so two windows that merely abut at the boundary instant do not conflict, and any genuine overlap is refused with `ERR_PERMIT_WINDOW_CONFLICT`. Alternatively a `REQUESTED` permit may be **denied**, moving it to `DENIED`. An `APPROVED` permit is **activated** to `ACTIVE`. An `ACTIVE` permit may be **expired** to `EXPIRED`. A permit may also be **revoked** to `REVOKED` from either `APPROVED` or `ACTIVE`. Each of these transitions increments the permit's `version`, and each is allowed only from its stated source state — otherwise `ERR_INVALID_STATE`. `EXPIRED`, `DENIED`, and `REVOKED` are terminal permit states.

### 3.8. Union Fringe Configuration

A `LineProducer` configures how each union's fringe is charged by creating a **union fringe** record for a production, supplying the `production_id`, the `union_code` (one of `SAG_AFTRA`, `IATSE`, or `DGA`), the `fringe_rate_bps` as a basis-point rate that must lie between 0 and 10000 inclusive, and an optional `pension_health_flat_cents` flat per-day contribution (zero or greater, defaulting to 0). At most one fringe configuration may exist per union per production: a second configuration for a `union_code` already configured on that production is refused with `ERR_DUPLICATE_FRINGE`. These configurations are what the estimate, fringe, and pay calculations of Section 3.5 read when they need a rate for a given crew member's union.

### 3.9. Residual Accrual

After a production earns money in distribution, the `PayrollCoordinator` records each earning as a **residual event** against the production, supplying the `production_id`, the `market` that generated it — one of `THEATRICAL`, `SVOD`, `BASIC_CABLE`, `NETWORK`, or `HOME_VIDEO` — the reported `gross_receipts_cents` (zero or greater), and the `event_date` in `YYYY-MM-DD` form. Recording the event computes its `residual_amount_cents` and adds that amount to the production's `residual_reserve_cents`.

The residual is accrued on the production's **cumulative** gross across all of its residual events, on a marginal tier schedule, so that early dollars and later dollars are rated differently. To compute a new event's residual, the system first sums the `gross_receipts_cents` of all of the production's earlier events — ordered by `event_date` ascending and then `created_at` ascending — to get the prior cumulative total, then adds this event's gross to get the new cumulative total. The residual for this event is the tier-rated value of the new cumulative total minus the tier-rated value of the prior cumulative total. The tier rating of any cumulative amount applies three marginal bands: the first 100,000,000 cents are rated at 120 basis points, the next 400,000,000 cents (the portion from 100,000,000 up to 500,000,000) are rated at 180 basis points, and every cent above 500,000,000 is rated at 240 basis points. Because the rating is applied to the cumulative total as a whole and then differenced, an event that straddles a tier boundary is rated partly at one band and partly at the next; this is the intended behavior and differs from naively rating each event in isolation at a single flat rate. The arithmetic is carried in whole cents.

A residual event is an immutable record: as noted in Section 2.4 it carries only an `id` and a `created_at` and has no `updated_at` or `version`.

### 3.10. Dailies Review

The `PostSupervisor` runs the **dailies** review pipeline. Footage is registered against a day with its `shooting_day_id` and a `reel_label`, opening in `PENDING`. Review **begins** by moving footage to `IN_REVIEW`, which is permitted from `PENDING` only while the parent day is `WRAPPED` or `IN_PROGRESS`, and which increments the dailies record's `version`. From `IN_REVIEW`, the supervisor either **approves** the footage to `APPROVED` or **flags** it. Flagging moves the footage from `IN_REVIEW` to `FLAGGED` and requires a `flagged_reason` to be supplied; flagging without a reason is refused with `ERR_DAILIES_FLAG_REASON_REQUIRED`. Flagged footage can be sent back into review — the same begin-review action takes `FLAGGED` back to `IN_REVIEW` — and this flag-then-review loop may repeat any number of times before the footage is finally approved. `APPROVED` footage is **archived** to the terminal `ARCHIVED` state. Each dailies transition increments the record's `version`, and any transition attempted from a non-matching source state is refused with `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including every state-transition action and every computed rollup — return a `200 OK` status code. The request body, response body, and side effects of each endpoint are described in the workflow narratives of Section 3; the table below is only an index of the HTTP surface.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/productions` | Create a production in DRAFT | LineProducer |
| GET | `/productions/{id}` | Fetch a production with computed cost fields | LineProducer, FirstAD, PayrollCoordinator, PostSupervisor, UnionRep |
| GET | `/productions` | List productions | LineProducer, FirstAD, PayrollCoordinator, PostSupervisor, UnionRep |
| POST | `/productions/{id}/advance` | Advance production lifecycle one step | LineProducer |
| POST | `/productions/{id}/close` | Close a WRAPPED production | LineProducer |
| GET | `/productions/{id}/budget-summary` | Computed budget-vs-actual rollup | LineProducer, PayrollCoordinator, UnionRep |
| POST | `/budget-lines` | Create a budget line under a production | LineProducer |
| GET | `/budget-lines/{id}` | Fetch a budget line | LineProducer, PayrollCoordinator, UnionRep |
| GET | `/budget-lines` | List budget lines | LineProducer, PayrollCoordinator, UnionRep |
| POST | `/budget-lines/{id}/post-actual` | Post a manual actual to a budget line | LineProducer |
| POST | `/shooting-days` | Create a planned shooting day | FirstAD |
| GET | `/shooting-days/{id}` | Fetch a shooting day | LineProducer, FirstAD, PayrollCoordinator, PostSupervisor, UnionRep |
| GET | `/shooting-days` | List shooting days | LineProducer, FirstAD, PayrollCoordinator, PostSupervisor, UnionRep |
| POST | `/shooting-days/{id}/start` | Move a CALLED day to IN_PROGRESS | FirstAD |
| POST | `/shooting-days/{id}/wrap` | Wrap an IN_PROGRESS day | FirstAD |
| POST | `/shooting-days/{id}/cancel` | Cancel a PLANNED or CALLED day | FirstAD |
| POST | `/scenes` | Create a script scene (unscheduled) | FirstAD |
| GET | `/scenes/{id}` | Fetch a scene | LineProducer, FirstAD, PostSupervisor, UnionRep |
| GET | `/scenes` | List scenes | LineProducer, FirstAD, PostSupervisor, UnionRep |
| POST | `/scenes/{id}/schedule` | Schedule a scene onto a PLANNED day | FirstAD |
| POST | `/crew-members` | Hire a crew/cast member | LineProducer |
| GET | `/crew-members/{id}` | Fetch a crew member | LineProducer, FirstAD, PayrollCoordinator, UnionRep |
| GET | `/crew-members` | List crew members | LineProducer, FirstAD, PayrollCoordinator, UnionRep |
| POST | `/assignments` | Book a crew member onto a day | FirstAD |
| GET | `/assignments/{id}` | Fetch an assignment with cost fields | LineProducer, FirstAD, PayrollCoordinator, UnionRep |
| GET | `/assignments` | List assignments | LineProducer, FirstAD, PayrollCoordinator, UnionRep |
| POST | `/assignments/{id}/check-in` | Check a crew member in | FirstAD |
| POST | `/assignments/{id}/check-out` | Wrap an assignment; stamp hours/penalties/fringe | FirstAD |
| POST | `/assignments/{id}/no-show` | Mark a scheduled assignment a no-show | FirstAD |
| POST | `/assignments/{id}/approve-pay` | Approve a wrapped assignment for payment | PayrollCoordinator |
| POST | `/assignments/{id}/mark-paid` | Mark an approved assignment paid | PayrollCoordinator |
| POST | `/call-sheets` | Create a DRAFT call sheet | FirstAD |
| GET | `/call-sheets/{id}` | Fetch a call sheet | LineProducer, FirstAD, PayrollCoordinator, PostSupervisor, UnionRep |
| GET | `/call-sheets` | List call sheets | LineProducer, FirstAD, PayrollCoordinator, PostSupervisor, UnionRep |
| POST | `/call-sheets/{id}/publish` | Publish a DRAFT or re-publish a REVISED sheet | FirstAD |
| POST | `/call-sheets/{id}/revise` | Revise a PUBLISHED call sheet | FirstAD |
| POST | `/call-sheets/{id}/finalize` | Finalize a PUBLISHED sheet after wrap | FirstAD |
| POST | `/locations` | Create a location under a production | LineProducer |
| GET | `/locations/{id}` | Fetch a location | LineProducer, FirstAD, UnionRep |
| GET | `/locations` | List locations | LineProducer, FirstAD, UnionRep |
| POST | `/location-permits` | Request a permit with an occupation window | LineProducer |
| GET | `/location-permits/{id}` | Fetch a permit | LineProducer, FirstAD, UnionRep |
| GET | `/location-permits` | List permits | LineProducer, FirstAD, UnionRep |
| POST | `/location-permits/{id}/approve` | Approve a requested permit | LineProducer |
| POST | `/location-permits/{id}/deny` | Deny a requested permit | LineProducer |
| POST | `/location-permits/{id}/activate` | Activate an approved permit | LineProducer |
| POST | `/location-permits/{id}/expire` | Expire an active permit | LineProducer |
| POST | `/location-permits/{id}/revoke` | Revoke an approved or active permit | LineProducer |
| POST | `/residual-events` | Record a residual-generating market event | PayrollCoordinator |
| GET | `/residual-events/{id}` | Fetch a residual event | PayrollCoordinator, LineProducer, UnionRep |
| GET | `/residual-events` | List residual events | PayrollCoordinator, LineProducer, UnionRep |
| POST | `/union-fringes` | Configure a union fringe rate | LineProducer |
| GET | `/union-fringes/{id}` | Fetch a union fringe config | LineProducer, PayrollCoordinator, UnionRep |
| GET | `/union-fringes` | List union fringe configs | LineProducer, PayrollCoordinator, UnionRep |
| POST | `/dailies` | Register dailies footage for a day | PostSupervisor |
| GET | `/dailies/{id}` | Fetch a dailies record | LineProducer, FirstAD, PostSupervisor, UnionRep |
| GET | `/dailies` | List dailies | LineProducer, FirstAD, PostSupervisor, UnionRep |
| POST | `/dailies/{id}/start-review` | Begin or resume review of footage | PostSupervisor |
| POST | `/dailies/{id}/approve` | Approve reviewed footage | PostSupervisor |
| POST | `/dailies/{id}/flag` | Flag reviewed footage for reshoot review | PostSupervisor |
| POST | `/dailies/{id}/archive` | Archive approved footage | PostSupervisor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CROSS_PRODUCTION_REFERENCE` | 409 Conflict |
| `ERR_DUPLICATE_DAY_NUMBER` | 409 Conflict |
| `ERR_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_PERMIT_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_CREW_TIME_CONFLICT` | 409 Conflict |
| `ERR_INVALID_TIME_RANGE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_FRINGE` | 409 Conflict |
| `ERR_BUDGET_WOULD_EXCEED` | 409 Conflict |
| `ERR_SCENE_SCHEDULE_LOCKED` | 409 Conflict |
| `ERR_VALIDATION_FAILED` | 422 Unprocessable Entity |
| `ERR_PAGINATION_INVALID` | 400 Bad Request |
| `ERR_DAILIES_FLAG_REASON_REQUIRED` | 422 Unprocessable Entity |
| `ERR_PRODUCTION_NOT_ACTIVE` | 409 Conflict |
| `ERR_OPEN_ASSIGNMENTS_BLOCK_WRAP` | 409 Conflict |

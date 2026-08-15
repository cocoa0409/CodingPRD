# Corporate Volunteer Day API — Product Requirements Document

## 1. Introduction

A corporate volunteer day looks simple from the outside — pick a nonprofit project, sign employees up, show up, take photos — but anyone who has run one knows the operational reality. Projects fall through when supplies never arrive on site. Minors cannot participate without a guardian-signed waiver, and a waiver signed against last month's document version no longer counts. Shuttle buses must be scheduled with turnaround time between runs, caterers cap how many meals one vendor can produce in a day, and a sponsor's per-hour pledge is only as honest as the verified attendance behind it. This document specifies the Corporate Volunteer Day API, the system of record a corporate community engagement team uses to plan, staff, fund, execute, and measure single-day team service events in partnership with nonprofit organizations.

The API governs the entire lifecycle: sourcing and vetting nonprofit partners' projects, matching them to a scheduled event, registering employee volunteers and collecting waivers, procuring supplies under segregation-of-duties controls, coordinating vehicles and meals against capacity limits, staffing qualified leads against supervision ratios, settling sponsorship pledges against actual attendance, and capturing impact and feedback afterward. Two system-wide ideas discipline everything else. First, every event carries a derived **readiness posture** — computed live from its projects, orders, meal plans, manifests, and registrations — that gates whether the event day may begin at all. Second, a **logical clock**, not the wall clock, drives every deadline in the system, so all temporal rules are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contract-level structures, and cross-cutting principles that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. A request missing either header, or carrying a role value the system does not recognize, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).

The system recognizes nine role values, spelled exactly as follows: `CommunityEngagementManager`, `NonprofitCoordinator`, `EmployeeVolunteer`, `StaffLead`, `ProcurementOfficer`, `LogisticsCoordinator`, `FinanceController`, `PlatformAdmin`, and `Any`. Every endpoint declares the roles authorized to invoke it; an authenticated caller whose role is not in an endpoint's list, or who fails an entity-backed ownership check, is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). The read-only listing and retrieval endpoints are open to any authenticated role, denoted `Any` in the endpoint table.

Roles differ in whether `X-User-ID` is a persisted entity identifier or an opaque operator handle:

- When `X-User-Role` is `EmployeeVolunteer`, `X-User-ID` is the `id` of the acting `EmployeeVolunteer`; ownership checks on any resource that references an `EmployeeVolunteer` compare the resource's foreign-key field — for example, a registration's `volunteer_id` — to `X-User-ID`. An `X-User-ID` that does not correspond to an existing volunteer is rejected with `ERR_VOLUNTEER_NOT_FOUND` (HTTP 404).
- When `X-User-Role` is `StaffLead`, `X-User-ID` is likewise the `id` of the acting `EmployeeVolunteer` (a staff lead is simply a volunteer flagged as lead-eligible); ownership checks on supervision assignments compare the assignment's `lead_volunteer_id` to `X-User-ID`, and an unresolved identifier is rejected with `ERR_VOLUNTEER_NOT_FOUND` (HTTP 404).
- When `X-User-Role` is `NonprofitCoordinator`, `X-User-ID` is the `id` of the acting `NonprofitPartner`; ownership checks on any resource that references a `NonprofitPartner` compare the resource's foreign-key field — for example, a project's `nonprofit_id` — to `X-User-ID`.
- When `X-User-Role` is `CommunityEngagementManager`, `ProcurementOfficer`, `LogisticsCoordinator`, `FinanceController`, `PlatformAdmin`, or `Any`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `created_by_user_id` on a `ProcurementOrder`, where it anchors the segregation-of-duties check — but does not compare it to any entity's `id`.

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

Requests to undefined paths or unsupported methods are likewise rejected in the error envelope, with `ERR_NOT_FOUND` (HTTP 404); an unexpected server failure surfaces as `ERR_INTERNAL` (HTTP 500).

---

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A `limit` or `offset` that is not an integer, a `limit` outside the range 1 to 100, or a negative `offset` is rejected with `ERR_VALIDATION` (HTTP 422).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order; resources sharing a `created_at` — common, since entity timestamps read the logical clock — are ordered by creation sequence, never by identifier. Filter query parameters match exactly and combine conjunctively; a filter that matches nothing yields an empty page, not an error.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Audit Fields

Every primary resource — nonprofit partners, service events, service projects, employee volunteers, registrations, procurement orders, vehicles, transport manifests, meal plans, supervision assignments, sponsorships, and impact records — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first persisted. Entity audit timestamps (`created_at` and `updated_at`) are stamped from the logical clock (§2.5), never the wall clock.
- `updated_at` (string): an ISO 8601 UTC timestamp, refreshed on any persisted change to the resource.
- `version` (integer): a system-managed optimistic-concurrency counter, starting at 1 on creation.

Feedback surveys are the single exception: a `FeedbackSurvey` is immutable once created and therefore carries only `id` and `created_at` — both `updated_at` and `version` are absent from it.

An entity's `version` increments by exactly one only on direct writes to that entity — its own create, action, and transition operations, including system-driven transitions whose from/to states live on that entity. Recomputation of a computed or derived field in the wake of a child or sibling mutation (headcounts, spend positions, readiness posture, hours credits, reputation aggregates) does not increment `version` by itself; `updated_at` refreshes on any persisted change regardless.

Client-supplied date and datetime inputs (`event_start_at`, `event_end_at`, `depart_at`, `return_at`, `date_of_birth`) are echoed in responses exactly as submitted; the server parses them for every temporal rule, normalizing any offset to UTC and treating a timezone-less value as UTC, and a date field also accepts a full datetime value, reduced to its calendar date.

### 2.5. The Logical Clock

All deadline and window validations in the system read a single logical clock, never the wall clock. At startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and before any explicit set call it continues to read that default; it never falls back to wall-clock time. The clock moves only through an admin-only test-driving capability restricted to `PlatformAdmin`, which advances the logical clock to a supplied `to_iso8601` instant (ISO 8601 UTC) and responds with the resulting `current_utc`; the supplied instant may be any valid ISO 8601 UTC time, and the clock is set exactly to it, whether that moves it forward or backward. Every rule phrased as "the current clock" or "now" in this document — the event-start lead time, the meal-order deadline, the manifest departure check, the feedback recency window — reads this logical clock.

### 2.6. Validation Pipeline and Check Ordering

When several checks could apply to one request, the server evaluates them in a fixed pipeline order rather than reporting whichever failure it happens to find first. The order, from first to last:

1. **Header context.** Presence of `X-User-ID` and `X-User-Role` and recognition of the role value, failing as `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Role authorization and ownership.** The acting role must be listed for the endpoint, and entity-backed ownership rules must hold: an `EmployeeVolunteer` acts only on their own registrations and surveys (the registration's `volunteer_id` must equal `X-User-ID`), a `NonprofitCoordinator` acts only on their own nonprofit's projects and impact records (the project's `nonprofit_id` must equal `X-User-ID`), and a `StaffLead` performing check-in must hold an `ACTIVE` supervision assignment on the registration's project. Violations surface as `ERR_FORBIDDEN_ROLE`, or `ERR_NOT_PROJECT_LEAD` for the staff-lead check-in case. Role-list authorization is evaluated immediately after the header context; an ownership comparison is evaluated once every resource it reads is in hand, so where ownership references a path- or body-addressed resource, that resource's existence check (steps 4–5) fires first — a dangling identifier surfaces as its `ERR_..._NOT_FOUND`, never as an ownership failure.
3. **Segregation of duties.** On procurement approval and rejection only, the approver must not be the order's creator, failing as `ERR_SEGREGATION_OF_DUTIES_VIOLATION`.
4. **Path existence.** Resource identifiers in the URL path are validated left to right (§2.10), failing as the corresponding `ERR_..._NOT_FOUND`.
5. **Body foreign-key existence.** Identifiers referenced in the request body (event, project, vehicle, manifest, registration, volunteer lead) must exist, again as the corresponding `ERR_..._NOT_FOUND`.
6. **State preconditions.** Each state machine's from-state requirement (the `ERR_INVALID_..._TRANSITION` family), event writable-state gates (`ERR_EVENT_STATE_FORBIDS_WRITE`), the partner-active gate (`ERR_NONPROFIT_SUSPENDED`), and stale-version rejections (`ERR_STALE_EVENT_VERSION`).
7. **Waiver and media safety gates.** Confirm requires a signed waiver (`ERR_WAIVER_NOT_SIGNED`), check-in requires a verified waiver (`ERR_WAIVER_NOT_VERIFIED`), a minor's signature requires a guardian (`ERR_GUARDIAN_SIGNATURE_REQUIRED`), and publishing media requires consent (`ERR_MEDIA_CONSENT_MISSING`).
8. **Supervision safety.** Creating a supervision assignment requires a qualified lead (`ERR_LEAD_NOT_QUALIFIED`); the lock-time supervision sufficiency check sits with the other lock gates in step 11.
9. **Temporal deadlines and windows.** Event start lead time (`ERR_EVENT_IN_PAST`), the meal-order deadline (`ERR_MEAL_ORDER_DEADLINE_PASSED`), manifest departure in the future (`ERR_MANIFEST_IN_PAST`), and related field-level time validation (`ERR_VALIDATION`).
10. **Vehicle window conflicts.** The thirty-minute turnaround rule, failing as `ERR_VEHICLE_SCHEDULE_CONFLICT`.
11. **Capacity and uniqueness.** Project capacity, manifest seats, vendor daily capacity, single active meal-plan pipeline, duplicate registration, duplicate supervision, one survey per registration, duplicate email, residual field validation, and — for project lock, in this order — the headcount floor (`ERR_MIN_VOLUNTEERS_NOT_MET`), supervision sufficiency (`ERR_INSUFFICIENT_SUPERVISION`), and site prep (`ERR_SITE_PREP_INCOMPLETE`).
12. **Cross-reference alignment.** Project-to-event, manifest-to-event, and impact-to-project alignment, plus eligibility gates such as checked-in registration, survey eligibility, rebook eligibility, unresolved sponsorships, and readiness.
13. **Fiscal gate.** Last of all, order approval checks the budget (`ERR_BUDGET_WOULD_EXCEED`).

The practical consequence: a confirm request that would fail both the waiver gate and the capacity gate surfaces `ERR_WAIVER_NOT_SIGNED`, because safety gates (step 7) precede capacity (step 11); an order approval that would breach the budget surfaces `ERR_BUDGET_WOULD_EXCEED` only after auth, existence, state, and every other check has passed, because the fiscal gate is evaluated last. Field-level failures — a missing required field, a value of the wrong type, an unparseable timestamp, an enum value outside its allowed set, a range violation such as a quantity or amount below its floor — are rejected with `ERR_VALIDATION` (HTTP 422). Request-body fields are parsed and shape-checked as the handler reads them, so a missing or malformed field surfaces ahead of any semantic check that follows the parse point; range and floor checks on well-formed values hold the pipeline positions shown above (event creation, for example, applies the step-9 temporal rule before the step-11 budget floor).

### 2.7. Event Readiness Posture

Every service event carries a derived `readiness_posture`, one of `BLOCKED`, `PARTIAL`, or `READY`, recomputed whenever any of its projects, registrations, supervision assignments, procurement orders, meal plans, or transport manifests changes. Posture is the single gate on beginning the event day (§3.7); it is never set directly by a client.

The derivation considers the event's active project set — its service projects currently in `MATCHED` or `LOCKED` status — together with demand and supply for meals and transport. Meal demand is the count of the event's registrations whose `rsvp_status` is `CONFIRMED` or `CHECKED_IN` and whose `wants_meal` flag is true. Transport demand is the count of the event's registrations whose `rsvp_status` is `CONFIRMED` or `CHECKED_IN` and whose `wants_transport` flag is true. Transport supply is the sum of `seat_capacity` over the vehicles of the event's transport manifests whose status is `CONFIRMED` or `COMPLETED`.

The posture is `BLOCKED` when the event has no project in `MATCHED` or `LOCKED` status at all. It is `READY` when all of the following hold simultaneously:

- at least one project in the active set is in `LOCKED` status;
- every project in the active set has `active_staff_leads` at least its `required_staff_leads`, and `confirmed_volunteer_count` at least its `min_volunteers`;
- no procurement order on the event is in `SUBMITTED` or `APPROVED` status;
- every `LOCKED` project in the active set has `site_prep_complete` equal to true;
- meal demand is zero, or at least one meal plan of the event is in `ORDERED` or `FULFILLED` status;
- transport demand is zero, or transport supply is at least transport demand.

In every other configuration the posture is `PARTIAL`. A posture that was `READY` therefore degrades to `PARTIAL` the moment any single condition breaks — a lead withdraws, a confirm pushes the supervision requirement above the staffed leads, an order goes back into the approval pipeline, a project demotes — which is exactly the mechanism that keeps an unready event from starting.

### 2.8. Fiscal Doctrine: Two Spend Positions and Cent Precision

All monetary quantities are integers of cents: `budget_cents`, `cost_cents`, `rate_cents`, `pledge_cap_cents`, `per_person_cost_cents`, `dietary_surcharge_cents`, `unit_cost_cents`, and every computed amount. Whenever a computation produces a fractional cent, the result is rounded half-up to whole cents; the reputation score is the lone two-decimal-place quantity in the system, also rounded half-up (§3.9), and hour quantities — an event's scheduled hours, a submitted `hours_attended`, and their sums — are rounded half-up to one decimal place, with sums exact.

Each event maintains two spend positions, recomputed immediately after every liability-affecting mutation (order submit, approve, reject, receive, or cancel; meal-plan order, cancel, or supersede; manifest create, confirm, or cancel; event cancellation cascade):

- `projected_spend_cents` is the forward-looking pipeline: the sum of `order_total_cents` over the event's procurement orders in `SUBMITTED`, `APPROVED`, or `RECEIVED` status, plus the sum of `total_cost_cents` over its meal plans in `ORDERED` or `FULFILLED` status, plus the sum of `cost_cents` over its transport manifests in `BOOKED`, `CONFIRMED`, or `COMPLETED` status.
- `committed_spend_cents` is the firmed-liability position: the sum of `order_total_cents` over orders in `APPROVED` or `RECEIVED` status, plus the sum of `total_cost_cents` over meal plans in `ORDERED` or `FULFILLED` status, plus the sum of `cost_cents` over manifests in `CONFIRMED` or `COMPLETED` status. Submitted-but-unapproved orders and booked-but-unconfirmed manifests are deliberately excluded.

`available_budget_cents` is the event's `budget_cents` minus its `projected_spend_cents` — the conservative availability figure, since it treats the whole pipeline as spent. The projected position is the one used for approval gating; the committed position feeds net-cost reporting and close-out (§3.8). Both positions start at zero on a new event.

### 2.9. Optimistic Concurrency Control

Two write operations on an event require the client to prove it has observed the event's current mutation state, by carrying `expected_event_version` — a non-optional input field holding the `version` of the `ServiceEvent` the client last read:

- Creating a meal plan for an event. Because creation supersedes the event's existing draft meal plan (§3.6), a writer whose last observed version is stale would silently cancel a plan it never saw; the create is therefore rejected instead.
- Rescheduling an event's window. The client's view of headcounts, posture, and deadlines is stale relative to the event's current mutation state once another write has advanced the version, so the reschedule is rejected.

In both cases, when `expected_event_version` does not match the event's current `version`, the request is rejected with `ERR_STALE_EVENT_VERSION` (HTTP 412). Endpoints other than these two do not take a version field.

### 2.10. Cascades, Mutation Semantics, and Nested Retrieval

The system maintains hierarchical consistency automatically. When a parent resource undergoes a transition that renders children non-operational — an event cancellation is the canonical case — the server transitions the affected children itself, without requiring explicit client requests on each child; conversely, mutations to children that break a parent's state criteria (a supervision withdrawal dropping a locked project below its staffing requirement) cause the server to demote the parent automatically. Each automatic transition of a given entity is a direct write to that entity for version purposes, while pure recomputation of derived fields on it is not (§2.4).

Batch and cascade side effects are applied deterministically: affected child entities are processed in ascending `created_at` order with ties broken by creation sequence, and no selector or tie-break ever uses random identifier values.

For requests that address nested resources — creating a meal plan under an event path is the one nested creation in the system — the system validates path identifiers in a strict left-to-right order and rejects immediately with the 404 error corresponding to the first identifier that does not resolve. A meal-plan creation under a non-existent event id therefore fails with `ERR_EVENT_NOT_FOUND` before any meal-plan rule is evaluated, and a registration addressed by a non-existent id fails with `ERR_REGISTRATION_NOT_FOUND` before its body is considered. The full not-found family — `ERR_NONPROFIT_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_VOLUNTEER_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, `ERR_MANIFEST_NOT_FOUND`, `ERR_MEAL_PLAN_NOT_FOUND`, `ERR_SUPERVISION_NOT_FOUND`, `ERR_SPONSORSHIP_NOT_FOUND`, `ERR_IMPACT_RECORD_NOT_FOUND`, and `ERR_SURVEY_NOT_FOUND` — is likewise used for body-referenced foreign keys that do not exist, checked after the path identifiers; within a body, foreign keys are checked in the order the endpoint's payload contract lists them (for an impact record, `registration_id` before `project_id`).

## 3. Business Logic & Workflows

### 3.1. Partner Onboarding and Project Sourcing

Everything begins with the nonprofit partners who supply the work. A `CommunityEngagementManager` registers a partner by providing its `name` and `contact_email`. A new partner starts in `ACTIVE` status with a null `reputation_score` (no surveys yet), a `survey_count` of zero, and a `completed_event_count` of zero — the count of events reaching `COMPLETED` or `CLOSED` that had at least one of this partner's projects completed. Partner listings can be filtered by `status`.

With a partner on the books, a `NonprofitCoordinator` proposes a service project through a payload carrying `nonprofit_id`, `title`, `min_volunteers`, `max_volunteers`, and optionally `required_skills`, an informational list of skill tags volunteers should have that defaults to empty. Ownership is enforced at the door: the coordinator's `X-User-ID` must equal the proposed `nonprofit_id`, otherwise the request is rejected with `ERR_FORBIDDEN_ROLE`. `min_volunteers` must be at least 1, and `max_volunteers` must be at least `min_volunteers`; violations of these ranges are rejected with `ERR_VALIDATION`. A partner in `SUSPENDED` status cannot source new work — proposing, and likewise vetting or matching, is rejected with `ERR_NONPROFIT_SUSPENDED`. A successfully proposed project starts in `PROPOSED` status, with `confirmed_volunteer_count`, `required_staff_leads`, and `active_staff_leads` all zero, `site_prep_complete` false, and a null `event_id` until it is matched.

A `CommunityEngagementManager` then vets a `PROPOSED` project, moving it to `VETTED`; the partner must still be `ACTIVE` (again `ERR_NONPROFIT_SUSPENDED`), and a project in any other from-state is rejected with `ERR_INVALID_PROJECT_TRANSITION`. Matching attaches a `VETTED` project to an event: the manager supplies the target `event_id`, the partner must be `ACTIVE`, and the target event must be in `PLANNING`, `REGISTRATION_OPEN`, or `REGISTRATION_LOCKED` status — a project cannot be attached to an event that is already running, finished, or cancelled, which is rejected with `ERR_EVENT_STATE_FORBIDS_WRITE`. Matching sets the project's `event_id` and recomputes the event's `readiness_posture`; the project is now `MATCHED`. Project listings may be filtered by `nonprofit_id`, `event_id`, or `status`.

A manager may cancel a project from `PROPOSED`, `VETTED`, `MATCHED`, or `LOCKED` — any other from-state is rejected with `ERR_INVALID_PROJECT_TRANSITION`. Cancellation is compensating: every non-terminal registration on the project moves to `CANCELLED` with its `transport_manifest_id` cleared, the project's `ACTIVE` supervision assignments move to `WITHDRAWN`, and the event's `readiness_posture` recomputes. The same cancellation also fires automatically, without a client request on the project, when the partner's reputation collapses — the auto-suspension cascade of §3.9 cancels the partner's `PROPOSED` and `VETTED` projects. `COMPLETED` and `CANCELLED` are the project's terminal states.

### 3.2. Building the Event: Creation, Rescheduling, and Repeat Booking

A `CommunityEngagementManager` creates an event by supplying its `name`, `event_start_at`, and `event_end_at` (both ISO 8601 UTC), a total `budget_cents` that may not be negative, and optionally the `waiver_document_version`, which defaults to 1 and must be at least 1. The start must be at least 24 hours after the current logical clock, and the end must be strictly after the start; either violation is rejected with `ERR_EVENT_IN_PAST` (HTTP 422). A new event opens in `PLANNING` status with `readiness_posture` `BLOCKED` (it has no matched projects yet), both spend positions at zero, all headcounts at zero, `total_scheduled_hours` and `total_verified_hours` at zero, a null `source_event_id`, `repeat_booking_bonus` false, and a null `avg_feedback_rating` until the first survey arrives.

Plans change, and an event's window can be rescheduled by a manager supplying a new `event_start_at`, a new `event_end_at`, and — per §2.9 — an `expected_event_version`. The same temporal rule applies: the new start must be at least 24 hours after the current logical clock, failing as `ERR_EVENT_IN_PAST`. A successful reschedule increments the event's `version` by 1. Rescheduling is not gated on the event's lifecycle status; the version match and the temporal rule are the only gates.

When a past event went well, a manager can repeat-book it: the rebook operation takes a `name`, `event_start_at`, `event_end_at`, and `budget_cents` for the new event and requires the source event to be in `COMPLETED` or `CLOSED` status, failing otherwise with `ERR_REBOOK_NOT_ELIGIBLE` (HTTP 409) — that eligibility check fires before the new event's `budget_cents` floor is validated, and the creation-time temporal rules (the 24-hour lead time and the end-after-start requirement) are not re-applied to the rebooked window. The new event is created in `PLANNING` with `waiver_document_version` 1 and its `source_event_id` pointing at the source — null on ordinary events, which makes the `source_event_id` filter on the event listing the way to find every repeat booking of a given source. The new event's `repeat_booking_bonus` is computed at creation: it is true when the source event has a non-null `avg_feedback_rating` of at least 4.0 and the new event's `event_start_at` is no later than 180 days after the source event's `event_start_at`, and false otherwise. The bonus's effect — a ten-percent uplift on sponsorship caps — is described in §3.8.

### 3.3. Volunteers, Staff Leads, and the Supervision Ratio

Employees join the program when a `CommunityEngagementManager` registers a volunteer profile with `full_name`, `email`, `department`, and `date_of_birth` (an ISO 8601 date), plus optional `skills` (skill tags, defaulting to empty), `dietary_tags`, and `is_staff_lead`. The `email` must be unique across all employee volunteers — a duplicate is rejected with `ERR_DUPLICATE_EMAIL` (HTTP 409). Each entry in `dietary_tags` must be one of `VEGETARIAN`, `VEGAN`, or `GLUTEN_FREE`; an empty list, the default, records no dietary need. The `is_staff_lead` flag, defaulting to false, marks the volunteer as eligible for supervision assignments. The volunteer listing can be filtered by `is_staff_lead`; the filter value must be the string `true` or `false`, and any other value is rejected with `ERR_VALIDATION`. Whether a volunteer counts as a minor is decided per event: a registration's `is_minor` is true when the volunteer's age, computed from `date_of_birth`, is under 18 at the event's `event_start_at`.

Every project needs staff supervision proportionate to its confirmed headcount, and the requirement is computed separately for adults and minors. Let the confirmed adults be the project's registrations with `rsvp_status` `CONFIRMED` or `CHECKED_IN` and `is_minor` false, and the confirmed minors the same set with `is_minor` true. When there are no confirmed volunteers at all, `required_staff_leads` is zero. Otherwise it is the confirmed adult count divided by 8 and rounded up to a whole number, plus the confirmed minor count divided by 4 and rounded up to a whole number — so exactly 8 confirmed adults need 1 lead while 9 need 2, and exactly 4 confirmed minors need 1 dedicated lead while 5 need 2. The requirement is recomputed on every confirm, cancel, and check-in-demotion cascade, on supervision creation and withdrawal, and at project lock.

A `CommunityEngagementManager` staffs a project by creating a supervision assignment with `project_id` and `lead_volunteer_id`. The project must be `MATCHED` or `LOCKED` — attempting to staff a project in any other status is rejected with `ERR_INVALID_PROJECT_TRANSITION`. The named lead must have `is_staff_lead` true and must not hold a non-`CANCELLED` registration on the same project (a lead cannot supervise a project they are also volunteering on); either failure is rejected with `ERR_LEAD_NOT_QUALIFIED`. Only one `ACTIVE` assignment may exist per project-and-lead pair; a duplicate is rejected with `ERR_ACTIVE_SUPERVISION_EXISTS`. The new assignment's `event_id` is copied from the project, its `status` starts `ACTIVE`, the project's `active_staff_leads` increases by one, and the event's posture is recomputed.

Withdrawal is shared between management and the lead: a `CommunityEngagementManager` may withdraw any assignment, and a `StaffLead` may withdraw their own — the caller's `X-User-ID` must equal the assignment's `lead_volunteer_id`, otherwise `ERR_FORBIDDEN_ROLE`. Only an `ACTIVE` assignment can be withdrawn (`ERR_INVALID_SUPERVISION_TRANSITION` otherwise). The withdrawal decrements the project's `active_staff_leads`, and if the project is `LOCKED` and now has fewer active leads than required, the project automatically demotes from `LOCKED` back to `MATCHED` and the event's posture is recomputed. Assignment listings filter by `project_id`, `event_id`, `lead_volunteer_id`, or `status`.

Once a project is staffed and stocked, a `CommunityEngagementManager` locks it, moving `MATCHED` → `LOCKED`; a project in any other from-state is rejected with `ERR_INVALID_PROJECT_TRANSITION`. Locking is the strictest gate in the project lifecycle, and its four preconditions are evaluated under the pipeline order of §2.6. First, the project's event must be in `REGISTRATION_OPEN` or `REGISTRATION_LOCKED` status — a project cannot be locked while its event is still `PLANNING` or already running — failing as `ERR_EVENT_STATE_FORBIDS_WRITE`. Second, the project's `confirmed_volunteer_count` must be at least its `min_volunteers`, otherwise the lock is rejected with `ERR_MIN_VOLUNTEERS_NOT_MET`. Third, supervision must be both present and sufficient: `required_staff_leads` must be at least 1, and `active_staff_leads` must be at least `required_staff_leads`, otherwise `ERR_INSUFFICIENT_SUPERVISION`. Fourth, `site_prep_complete` must be true — at least one of the project's orders received and none still in the approval pipeline, per §3.5 — otherwise `ERR_SITE_PREP_INCOMPLETE`. A successful lock recomputes the event's `readiness_posture`, and because a locked project is one of the posture's `READY` conditions, locking is usually the action that turns an event `READY`.

### 3.4. Registration, Waivers, and the Road to Check-In

Participation starts when an `EmployeeVolunteer` self-registers, submitting `event_id` and `project_id` with optional `wants_transport` (default false) and `wants_meal` (default true); the server takes the registration's `volunteer_id` from the caller's `X-User-ID`. The event must be in `PLANNING`, `REGISTRATION_OPEN`, or `REGISTRATION_LOCKED` status, otherwise `ERR_EVENT_STATE_FORBIDS_WRITE`. The project must belong to the same event — a mismatch is rejected with `ERR_PROJECT_EVENT_MISMATCH` (HTTP 422) — and must currently be `MATCHED` or `LOCKED` to that event, otherwise `ERR_INVALID_PROJECT_TRANSITION`. One non-`CANCELLED` registration per volunteer per event is the uniqueness rule: a second live registration for the same pair is rejected with `ERR_DUPLICATE_REGISTRATION`. A new registration starts with `rsvp_status` `REGISTERED` and `waiver_status` `WAIVER_PENDING`, with `waiver_signed_version`, `waiver_signer_relation`, `waiver_signer_name`, and `checked_in_at` all null, `media_consent` false, `transport_manifest_id` null, and both hours credits at zero; the event's headcounts recompute immediately.

The event tracks three headcounts over its registrations: `registered_headcount` counts `rsvp_status` `REGISTERED`, `CONFIRMED`, or `CHECKED_IN`; `confirmed_headcount` counts `CONFIRMED` or `CHECKED_IN`; `checked_in_headcount` counts only `CHECKED_IN`. Registration listings filter by `event_id`, `volunteer_id`, `project_id`, `transport_manifest_id`, or `rsvp_status`.

A registration lives on two independent state dimensions. The RSVP dimension runs `REGISTERED` → `CONFIRMED` → `CHECKED_IN`, with `CANCELLED` and `NO_SHOW` as terminal outcomes. The waiver dimension runs `WAIVER_PENDING` → `WAIVER_SIGNED` → `WAIVER_VERIFIED`, with `WAIVER_VOIDED` as the reset state. One dimension never substitutes for the other — confirm and check-in each look at both.

**Signing the waiver.** The volunteer signs by submitting `signer_name`, `signer_relation`, `media_consent`, and, when a guardian signs, `guardian_name`. Signing is possible from either `WAIVER_PENDING` or `WAIVER_VOIDED` — a voided waiver can be re-signed against the current document version — and only while the event is in `REGISTRATION_OPEN`, `REGISTRATION_LOCKED`, or `IN_PROGRESS` status, failing otherwise with `ERR_EVENT_STATE_FORBIDS_WRITE`. The guardian rule is strict: for a registration whose `is_minor` is true, `signer_relation` must be `GUARDIAN` and `guardian_name` must be non-empty, otherwise the request is rejected with `ERR_GUARDIAN_SIGNATURE_REQUIRED` (HTTP 422); for an adult, `signer_relation` must be `SELF`, and any other value is rejected with `ERR_VALIDATION`. A successful signing records `waiver_signed_version` as the event's current `waiver_document_version` at that moment, stores the signer identity in `waiver_signer_name` (the `guardian_name` when a guardian signs, otherwise the `signer_name`) and `waiver_signer_relation`, and captures `media_consent`, the flag that later gates photo and story publication (§3.9). Any other from-state in the waiver dimension is rejected with `ERR_INVALID_REGISTRATION_TRANSITION`. A manager then verifies a `WAIVER_SIGNED` waiver, moving it to `WAIVER_VERIFIED`.

**Confirming a seat.** Confirmation is a manager-only action with five preconditions, which the pipeline orders as state first, safety next, capacity last: the registration must be in `REGISTERED` (`ERR_INVALID_REGISTRATION_TRANSITION` otherwise), the event must be in `REGISTRATION_OPEN` or `REGISTRATION_LOCKED` (`ERR_EVENT_STATE_FORBIDS_WRITE`), the project must be `MATCHED` or `LOCKED` (`ERR_INVALID_PROJECT_TRANSITION`), the waiver must be `WAIVER_SIGNED` or `WAIVER_VERIFIED` (`ERR_WAIVER_NOT_SIGNED`), and the project's `confirmed_volunteer_count` must be below its `max_volunteers` (`ERR_PROJECT_AT_CAPACITY`). A successful confirm increments the project's `confirmed_volunteer_count` by one and recomputes `required_staff_leads` per the supervision rule; if the project was `LOCKED` and the new requirement now exceeds `active_staff_leads`, the project automatically demotes `LOCKED` → `MATCHED` and the event's posture is recomputed. Event headcounts recompute as well.

**Cancelling a seat.** A registration can be cancelled from `REGISTERED` or `CONFIRMED` — other states are `ERR_INVALID_REGISTRATION_TRANSITION` — by a manager, or by the volunteer themselves, in which case the caller's `X-User-ID` must equal the registration's `volunteer_id` (`ERR_FORBIDDEN_ROLE` otherwise). Cancelling clears `transport_manifest_id`, freeing the seat on the manifest. When the cancelled registration had been `CONFIRMED`, the project's `confirmed_volunteer_count` decrements and `required_staff_leads` recomputes; if the project was `LOCKED` and the confirmed count has fallen below `min_volunteers`, the project demotes `LOCKED` → `MATCHED`, and the event's posture recomputes.

**Check-in on the day.** With the event `IN_PROGRESS`, a confirmed volunteer is checked in by a manager or by a `StaffLead`; an event in any other status rejects the check-in with `ERR_EVENT_STATE_FORBIDS_WRITE`, and a registration not in `CONFIRMED` rejects with `ERR_INVALID_REGISTRATION_TRANSITION`. The waiver must have reached `WAIVER_VERIFIED` — a merely signed waiver is not enough on the day — failing as `ERR_WAIVER_NOT_VERIFIED`. A staff-lead caller must hold an `ACTIVE` supervision assignment on the registration's project, otherwise `ERR_NOT_PROJECT_LEAD` (HTTP 403). Check-in stamps `checked_in_at` with the current logical clock and sets the registration's `scheduled_hours_credit` to the event's scheduled hours — the duration from `event_start_at` to `event_end_at` expressed in hours, such as 6.0 for a six-hour day — while a registration that never checks in keeps zero scheduled credit. The event's `checked_in_headcount` and posture recompute.

**Rotating the waiver document.** When the legal text changes mid-cycle, a manager advances the event's `waiver_document_version` by exactly 1. Every waiver whose `waiver_signed_version` is below the new version and currently `WAIVER_SIGNED` or `WAIVER_VERIFIED` is automatically moved to `WAIVER_VOIDED`. Each affected registration whose `rsvp_status` was `CONFIRMED` demotes back to `REGISTERED`, decrementing the project's `confirmed_volunteer_count` and recomputing `required_staff_leads`; when a `LOCKED` project thereby falls below `min_volunteers` or has its requirement exceed its active leads, it demotes `LOCKED` → `MATCHED`. The event's posture recomputes and its `version` increments by 1. Affected volunteers restore their standing by signing again under the new version, per the signing rules above.

### 3.5. Procurement, Budgets, and Site Preparation

Supplies and tools reach the site through procurement orders. A `CommunityEngagementManager` creates an order with `event_id`, `project_id`, and a `lines` array of at least one line, each line carrying an `item_name`, a `quantity` of at least 1, and a `unit_cost_cents` of at least 0. The project must belong to the same event as the order's `event_id`, otherwise `ERR_PROJECT_EVENT_MISMATCH`, and the event must be in `PLANNING`, `REGISTRATION_OPEN`, or `REGISTRATION_LOCKED`, otherwise `ERR_EVENT_STATE_FORBIDS_WRITE`. At creation the server computes `order_total_cents` and freezes it: each line's extended cost is its `quantity` multiplied by its `unit_cost_cents` and by one plus the 8.75% tax rate, rounded half-up to whole cents, and the order total is the sum of those per-line rounded amounts. Rounding each line first and then summing is mandatory — summing the unrounded line products and rounding once at the end produces different cents and is not permitted. The new order starts in `DRAFT` status, with `created_by_user_id` recorded from the caller's `X-User-ID` and `rejection_reason` null. Order listings filter by `event_id`, `project_id`, or `status`.

Submission moves an order from `DRAFT` to `SUBMITTED` — and, because rejection is not terminal for the workflow, resubmission also moves a `REJECTED` order back to `SUBMITTED`, clearing its `rejection_reason` to null — with the same event writable-state gate (`ERR_EVENT_STATE_FORBIDS_WRITE`) and the usual from-state guard (`ERR_INVALID_ORDER_TRANSITION`); the order now enters the event's projected spend. Approval and rejection belong exclusively to a `ProcurementOfficer`, and segregation of duties is enforced on both: the caller's `X-User-ID` must differ from the order's `created_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403). Approval additionally requires the event to be in `PLANNING`, `REGISTRATION_OPEN`, or `REGISTRATION_LOCKED` (`ERR_EVENT_STATE_FORBIDS_WRITE`) and passes through the fiscal gate last: the event's `projected_spend_cents` — which already includes this order, since it is `SUBMITTED` — must not exceed the event's `budget_cents`, otherwise the approval is rejected with `ERR_BUDGET_WOULD_EXCEED` (HTTP 402). An approved order enters committed spend and blocks readiness until it arrives (§2.7's prohibition on `SUBMITTED` or `APPROVED` orders). Rejection records the supplied `rejection_reason` and drops the order back out of projected spend.

Receipt is the manager's confirmation that goods arrived: an `APPROVED` order moves to `RECEIVED`, which recomputes the project's `site_prep_complete`, the event's spend, and posture. A project's `site_prep_complete` is true exactly when at least one procurement order for the project has reached `RECEIVED` and no order for the project remains in `SUBMITTED` or `APPROVED` — supplies both delivered and settled, with nothing still in the pipeline. Cancellation is available from `DRAFT`, `SUBMITTED`, or `APPROVED` and moves the order to `CANCELLED` with a budget reversal; `RECEIVED` orders are terminal and cannot be cancelled.

### 3.6. Moving and Feeding People: Vehicles, Manifests, and Meal Plans

The logistics side of the program belongs to the `LogisticsCoordinator`, beginning with the fleet: a vehicle is registered with a `name` (a label such as Bus-7) and a `seat_capacity` of at least 1.

Booking a vehicle window for an event creates a transport manifest from `event_id`, `vehicle_id`, `depart_at`, `return_at`, and `cost_cents` (which may not be negative). The `depart_at` must be strictly after the current logical clock (`ERR_MANIFEST_IN_PAST`, HTTP 422), and `return_at` must be strictly after `depart_at` (`ERR_VALIDATION`). The same vehicle cannot be double-booked: against every existing manifest for that vehicle in `BOOKED`, `CONFIRMED`, or `COMPLETED` status, the new window must respect a 30-minute turnaround buffer, meaning there is no conflict only when the new departure is at or after the existing window's return plus 30 minutes, or the new return plus 30 minutes is at or before the existing departure. Adjacency at exactly the 30-minute buffer is legal; one minute less is a conflict, rejected with `ERR_VEHICLE_SCHEDULE_CONFLICT`. A booked manifest starts in `BOOKED` status with `assigned_seats` zero, and its `cost_cents` already counts toward projected spend. Confirmation moves it `BOOKED` → `CONFIRMED`, promoting the cost into committed spend; cancelling from `BOOKED` or `CONFIRMED` moves it to `CANCELLED`, clears `transport_manifest_id` on every registration pointing at it, frees the vehicle window, and reverses the spend — other from-states fail as `ERR_INVALID_MANIFEST_TRANSITION`. Manifest listings filter by `event_id`, `vehicle_id`, or `status`.

Seats are allocated one registration at a time: the coordinator assigns a registration to a manifest by supplying `transport_manifest_id`. The manifest must belong to the same event as the registration (`ERR_MANIFEST_EVENT_MISMATCH`, HTTP 422), must be in an assignable non-terminal state — `BOOKED` or `CONFIRMED`, since a `CANCELLED` or `COMPLETED` manifest rejects the assignment with `ERR_INVALID_MANIFEST_TRANSITION` — and must have a free seat: the manifest's `assigned_seats`, the count of registrations pointing at it with `rsvp_status` `REGISTERED`, `CONFIRMED`, or `CHECKED_IN`, must be below the vehicle's `seat_capacity`, otherwise `ERR_MANIFEST_FULL`. Assignment does not gate on the registration's own `rsvp_status`; it sets the registration's `transport_manifest_id` and recomputes the manifest's `assigned_seats`, and a seat is consumed only while the assigned registration counts toward `assigned_seats`.

Meals run on their own pipeline. The coordinator creates the event's meal plan with `vendor_name`, a `per_person_cost_cents` of at least 1, an optional `dietary_surcharge_cents` defaulting to 0 and never negative, and — per §2.9 — a mandatory `expected_event_version`; a stale value is rejected with `ERR_STALE_EVENT_VERSION` (HTTP 412). The plan's `event_id` comes from the request path. Only one active meal pipeline exists per event: if a plan in `ORDERED` or `FULFILLED` status already exists for the event, creation is rejected with `ERR_ACTIVE_MEAL_PLAN_EXISTS`; if a `DRAFT` plan exists, creating the new plan supersedes it — the old draft moves to `CANCELLED` — and the creation increments the event's `version` by 1. The new plan starts in `DRAFT` with `ordered_headcount`, `dietary_headcount`, and `total_cost_cents` all null until the order is placed. Meal-plan listings filter by `event_id`, `vendor_name`, or `status`.

Placing the order freezes the numbers. Ordering requires the plan to be `DRAFT` (`ERR_INVALID_MEAL_PLAN_TRANSITION` otherwise) and the current logical clock to be no later than 72 hours before the event's `event_start_at` — the caterer's lead time — failing as `ERR_MEAL_ORDER_DEADLINE_PASSED`. At that moment the server snapshots the eligible diners: `ordered_headcount` counts the event's registrations with `rsvp_status` `CONFIRMED` or `CHECKED_IN` and `wants_meal` true, and `dietary_headcount` counts the subset carrying at least one dietary tag. An empty table is not an order — a snapshot of zero is rejected with `ERR_NO_MEAL_HEADCOUNT`. The plan's `total_cost_cents` is the number of non-dietary diners multiplied by `per_person_cost_cents`, plus the number of dietary diners multiplied by the sum of `per_person_cost_cents` and `dietary_surcharge_cents`. One more constraint protects the caterer: across all meal plans with the same `vendor_name` whose events share the same UTC calendar date of `event_start_at` and whose status is `ORDERED` or `FULFILLED`, the pooled `ordered_headcount` plus this plan's snapshot must not exceed the vendor's daily capacity of 6 meals, otherwise the order is rejected with `ERR_VENDOR_CAPACITY_EXCEEDED`. Ordering moves the plan to `ORDERED` and recomputes spend and posture.

Fulfillment records that the food was served: a manual fulfillment moves `ORDERED` → `FULFILLED` and additionally requires the event to be `IN_PROGRESS` or `COMPLETED` (`ERR_EVENT_STATE_FORBIDS_WRITE` otherwise); the event-completion cascade (§3.7) fulfills any still-`ORDERED` plans automatically. Cancelling from `DRAFT` or `ORDERED` moves the plan to `CANCELLED` and reverses its spend.

### 3.7. The Event Day: Begin, Complete, Close, and Cancel

The event lifecycle proper is a manager-driven spine: opening registration moves `PLANNING` → `REGISTRATION_OPEN`, locking registration moves `REGISTRATION_OPEN` → `REGISTRATION_LOCKED`, beginning the day moves `REGISTRATION_LOCKED` → `IN_PROGRESS`, completing moves `IN_PROGRESS` → `COMPLETED`, and closing moves `COMPLETED` → `CLOSED`. Each of these actions is legal only from its named from-state — anything else is `ERR_INVALID_EVENT_TRANSITION` — and each increments the event's `version` by exactly 1.

Beginning the day is the posture-gated step: beyond being `REGISTRATION_LOCKED`, the event's `readiness_posture` must be `READY` at that instant, otherwise the begin is rejected with `ERR_EVENT_NOT_READY`. This is where every thread of §3 converges — locked and supervised projects, delivered supplies, ordered meals, sufficient confirmed seats.

Completion is the day's reconciling cascade. Along with the version increment and a full recompute of headcounts, spend, and posture, completing the event moves every registration still in `CONFIRMED` to `NO_SHOW` (the volunteers who never checked in; their `transport_manifest_id` is cleared), every `LOCKED` project of the event to `COMPLETED`, every manifest in `BOOKED` or `CONFIRMED` to `COMPLETED`, and every meal plan in `ORDERED` to `FULFILLED`.

Closing is the financial gate: the event must be `COMPLETED`, and every sponsorship of the event must have reached a terminal state — `SETTLED` or `WITHDRAWN`; outstanding pledges or commitments reject the close with `ERR_UNRESOLVED_SPONSORSHIPS`. `CLOSED` and `CANCELLED` are the event's terminal states.

Cancellation is the full compensating unwind, available from `PLANNING`, `REGISTRATION_OPEN`, or `REGISTRATION_LOCKED` (else `ERR_INVALID_EVENT_TRANSITION`), with each child cascade applied in ascending `created_at` order (§2.10): the event's registrations in `REGISTERED` or `CONFIRMED` move to `CANCELLED` with `transport_manifest_id` cleared; its procurement orders in `DRAFT`, `SUBMITTED`, or `APPROVED` move to `CANCELLED` as a budget reversal while `RECEIVED` orders are untouched; its manifests in `BOOKED` or `CONFIRMED` move to `CANCELLED`; its meal plans in `DRAFT` or `ORDERED` move to `CANCELLED`; its sponsorships in `PLEDGED` or `COMMITTED` move to `WITHDRAWN`; its projects in `MATCHED` or `LOCKED` return to `VETTED` with `event_id` cleared to null, releasing them back to the sourcing pool, and each such project's `ACTIVE` supervision assignments move to `WITHDRAWN`; and the event's `version` increments by 1.

### 3.8. Sponsorship Pledges, Settlement, and Net Event Cost

Corporate sponsors attach money to an event through sponsorships, owned end to end by the `FinanceController`. A pledge is created with `event_id`, `sponsor_name`, a `match_type` of `FLAT`, `PER_CHECK_IN`, or `PER_VERIFIED_HOUR`, a `rate_cents` of at least 1 — the flat amount for `FLAT`, or the per-unit rate in cents per check-in or per verified hour — and a `pledge_cap_cents` of at least 1, the donation cap before any repeat-booking uplift. A new sponsorship starts in `PLEDGED` with `provisional_amount_cents` zero and `settled_amount_cents` null until settlement. Sponsorship listings filter by `event_id` or `status`.

The cap a sponsor's money is actually capped at is `effective_cap_cents`: when the event's `repeat_booking_bonus` is true, it is `pledge_cap_cents` increased by 10 percent and rounded half-up to whole cents; otherwise it equals `pledge_cap_cents`.

While a sponsorship is `PLEDGED` or `COMMITTED`, its `provisional_amount_cents` is a live, forward-looking estimate, recomputed on any headcount or hours change. The estimate's base depends on `match_type`: for `FLAT`, the base is simply `rate_cents`; for `PER_CHECK_IN`, the base is `rate_cents` multiplied by the event's `confirmed_headcount` (confirmed plus checked-in registrations); for `PER_VERIFIED_HOUR`, the base is `rate_cents` multiplied by the event's `confirmed_headcount` multiplied by the event's scheduled hours — the duration from `event_start_at` to `event_end_at` in hours — rounded half-up to whole cents. The provisional amount is the smaller of that base and `effective_cap_cents`. Committing moves the pledge `PLEDGED` → `COMMITTED` and brings the provisional amount into the event's sponsorship credit.

Settlement converts the estimate into chronological actuals, and is only possible once the event is `COMPLETED` or `CLOSED` — settling earlier is rejected with `ERR_EVENT_STATE_FORBIDS_WRITE`. At settle time `settled_amount_cents` is computed on the actuals: for `FLAT`, the base is `rate_cents`; for `PER_CHECK_IN`, the base is `rate_cents` multiplied by the event's `checked_in_headcount` — actual check-ins only, so a no-show who was counted in the provisional estimate drops out; for `PER_VERIFIED_HOUR`, the base is `rate_cents` multiplied by the event's `total_verified_hours`, rounded half-up to whole cents. The settled amount is again the smaller of the base and `effective_cap_cents`. Settlement moves the sponsorship `COMMITTED` → `SETTLED` and recomputes the event's sponsorship totals and net cost. A `FinanceController` may also withdraw a sponsorship from `PLEDGED` or `COMMITTED`, moving it to `WITHDRAWN` with the credit reversed; event cancellation drives the same withdrawal automatically. Every other from-state combination in the sponsorship lifecycle is rejected with `ERR_INVALID_SPONSORSHIP_TRANSITION`.

The event's net cost is computed in a fixed evaluation order, because the sponsorship credit reduces net cost while the offset itself is capped by gross spend. First, gross is the event's `committed_spend_cents` from §2.8. Second, the credit is the sum over the event's sponsorships of `settled_amount_cents` for those `SETTLED` and `provisional_amount_cents` for those `COMMITTED`; `PLEDGED` and `WITHDRAWN` sponsorships contribute zero. Third, the offset is the smaller of that credit and one half of gross rounded half-up to whole cents — sponsors can defray at most half the committed spend. Fourth, `net_event_cost_cents` is gross minus the offset. The credit from the second step is exposed on the event as `sponsorship_credit_cents`.

### 3.9. Impact Capture, Feedback, and Partner Reputation

After the work is done, the nonprofit documents what happened. A `NonprofitCoordinator` submits an impact record with `registration_id`, `project_id`, and `hours_attended`, plus optional `photo_count` (default 0, never negative) and optional `story_text` (default empty, meaning no story). Ownership applies: the coordinator's `X-User-ID` must equal the `nonprofit_id` of the project named in the record, otherwise `ERR_FORBIDDEN_ROLE`. The named `project_id` must equal the registration's own `project_id` (`ERR_IMPACT_PROJECT_MISMATCH`, HTTP 422), and the registration must be in `CHECKED_IN` — impact cannot be claimed for someone who never arrived — failing as `ERR_REGISTRATION_NOT_CHECKED_IN`. The claimed `hours_attended` must be greater than zero and no more than the event's scheduled hours, otherwise `ERR_VALIDATION`. The record's `event_id` is copied from its registration, and it starts in `SUBMITTED` status with `rejection_reason` null. Impact-record listings filter by `registration_id`, `project_id`, `event_id`, or `status`.

Moderation belongs to the `CommunityEngagementManager`. Verification moves `SUBMITTED` → `VERIFIED` and recomputes verified hours everywhere: the registration's `verified_hours_credit` — the sum of its own impact records' `hours_attended` in `VERIFIED` or `PUBLISHED` status — and the event's `total_verified_hours`, the same sum across all impact records of the event. Publication moves `VERIFIED` → `PUBLISHED`, the record's terminal state, and carries the media-consent gate: when the record's `photo_count` is greater than zero or its `story_text` is non-empty, the registration's `media_consent` must be true, otherwise the publish is rejected with `ERR_MEDIA_CONSENT_MISSING`. Rejection moves a record from `SUBMITTED` or `VERIFIED` to `REJECTED`, recording the supplied `rejection_reason`; rejecting a previously `VERIFIED` record reverses its hours out of both verified-hours totals. The nonprofit may then resubmit: a `REJECTED` record returns to `SUBMITTED`, its `rejection_reason` cleared to null, performed by a `NonprofitCoordinator` whose `X-User-ID` equals the project's `nonprofit_id` (`ERR_FORBIDDEN_ROLE` otherwise). Any other from-state in this lifecycle is rejected with `ERR_INVALID_IMPACT_TRANSITION`.

The dual hours accounting is deliberate: a checked-in volunteer's `scheduled_hours_credit` reflects the full event window keyed on the check-in flag, while `verified_hours_credit` reflects only what the nonprofit claimed and staff verified. The event mirrors both as `total_scheduled_hours` — the sum of scheduled credits over its registrations — and `total_verified_hours`, and the two legitimately diverge: a volunteer checked in for a 6.0-hour day with 2.5 verified hours shows 6.0 scheduled against 2.5 verified.

Finally, volunteers close the loop. An `EmployeeVolunteer` submits one feedback survey per registration, carrying `registration_id`, a `rating` from 1 to 5 inclusive, `would_repeat` — whether they would volunteer with this nonprofit again — and optional `comments` defaulting to empty. The registration must be the caller's own (`ERR_FORBIDDEN_ROLE`), must be in `CHECKED_IN`, and its event must be `COMPLETED` or `CLOSED`; the eligibility failures are rejected with `ERR_SURVEY_NOT_ELIGIBLE`, and a second survey for the same registration with `ERR_ONE_SURVEY_PER_REGISTRATION`. Survey listings filter by `registration_id`.

Each survey feeds two aggregates. The event's `avg_feedback_rating` is the mean of `rating` over the surveys of its registrations, rounded half-up to two decimal places and null until the first survey — the value §3.2's repeat-booking bonus reads. The partner's `reputation_score` is recency-weighted: over all surveys reachable from the partner through registration to project (only checked-in registrations ever have surveys, per the eligibility rule), a survey's weight is 1.0 when it was created within the 90 days preceding the current logical clock — a survey created exactly 90 days before the current clock still counts as recent — and 0.5 when older; the score is the sum of each rating multiplied by its weight, divided by the sum of the weights, rounded half-up to two decimal places, and null while no surveys exist. The partner's `survey_count` is the size of that survey set.

Reputation has teeth, applied automatically on survey creation with a hysteresis band so partners do not flap between states: when `survey_count` is at least 3 and `reputation_score` falls below 2.50, the partner moves from `ACTIVE` to `SUSPENDED`, and that suspension cascades — the partner's projects in `PROPOSED` or `VETTED` move to `CANCELLED`, while `MATCHED`, `LOCKED`, and `COMPLETED` projects are untouched; when `reputation_score` is 3.00 or higher, the partner moves from `SUSPENDED` back to `ACTIVE`. Scores in the band between 2.50 and 3.00 trigger no transition. A suspended partner, per §3.1, cannot source, vet, or match projects until reinstated.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — lifecycle actions, assignments, verifications — return `200 OK`. All responses use the envelope of §2.2, and all list endpoints paginate per §2.3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/nonprofit-partners` | Register a nonprofit partner (`name`, `contact_email`); starts `ACTIVE` with null reputation | CommunityEngagementManager |
| GET | `/nonprofit-partners` | List nonprofit partners; filters: `status` | Any |
| GET | `/nonprofit-partners/{partnerId}` | Get a nonprofit partner | Any |
| POST | `/service-projects` | Nonprofit proposes a project (`nonprofit_id`, `title`, `min_volunteers`, `max_volunteers`, optional `required_skills`); starts `PROPOSED` | NonprofitCoordinator |
| GET | `/service-projects` | List projects; filters: `nonprofit_id`, `event_id`, `status` | Any |
| GET | `/service-projects/{projectId}` | Get a project | Any |
| POST | `/service-projects/{projectId}/vet` | Vet a proposed project (`PROPOSED` → `VETTED`) | CommunityEngagementManager |
| POST | `/service-projects/{projectId}/match` | Match a vetted project to an event (`event_id`); `VETTED` → `MATCHED`, posture recompute | CommunityEngagementManager |
| POST | `/service-projects/{projectId}/lock` | Lock a matched project — supervision, headcount, and site-prep gates; `MATCHED` → `LOCKED` | CommunityEngagementManager |
| POST | `/service-projects/{projectId}/cancel` | Cancel a project; cascades registrations and supervision, posture recompute | CommunityEngagementManager |
| POST | `/service-events` | Create an event (`name`, `event_start_at`, `event_end_at`, `budget_cents`, optional `waiver_document_version`); starts `PLANNING`, posture `BLOCKED` | CommunityEngagementManager |
| GET | `/service-events` | List events; filters: `status`, `source_event_id` (finds repeat bookings of a source event) | Any |
| GET | `/service-events/{eventId}` | Get an event with all computed fields | Any |
| POST | `/service-events/{eventId}/open-registration` | Open registration (`PLANNING` → `REGISTRATION_OPEN`) | CommunityEngagementManager |
| POST | `/service-events/{eventId}/lock-registration` | Lock registration (`REGISTRATION_OPEN` → `REGISTRATION_LOCKED`) | CommunityEngagementManager |
| POST | `/service-events/{eventId}/begin` | Begin the event day (`REGISTRATION_LOCKED` → `IN_PROGRESS`); requires posture `READY` | CommunityEngagementManager |
| POST | `/service-events/{eventId}/complete` | Complete the event; no-show, project, manifest, and meal-plan completion cascade | CommunityEngagementManager |
| POST | `/service-events/{eventId}/close` | Close the event (`COMPLETED` → `CLOSED`); requires sponsorships terminal | CommunityEngagementManager |
| POST | `/service-events/{eventId}/cancel` | Cancel the event with the full compensating cascade | CommunityEngagementManager |
| POST | `/service-events/{eventId}/reschedule` | Reschedule the event window (`event_start_at`, `event_end_at`, `expected_event_version`; OCC) | CommunityEngagementManager |
| POST | `/service-events/{eventId}/bump-waiver-version` | Advance `waiver_document_version` by 1; voids stale signed/verified waivers and demotes affected registrations | CommunityEngagementManager |
| POST | `/service-events/{eventId}/rebook` | Repeat-book a new event (`name`, `event_start_at`, `event_end_at`, `budget_cents`) from a `COMPLETED`/`CLOSED` source | CommunityEngagementManager |
| POST | `/employee-volunteers` | Register an employee volunteer (`full_name`, `email`, `department`, `date_of_birth`, optional `skills`, `dietary_tags`, `is_staff_lead`) | CommunityEngagementManager |
| GET | `/employee-volunteers` | List volunteers; filters: `is_staff_lead` | Any |
| GET | `/employee-volunteers/{volunteerId}` | Get a volunteer | Any |
| POST | `/registrations` | Volunteer self-registers for a project at an event (`event_id`, `project_id`, optional `wants_transport`, `wants_meal`) | EmployeeVolunteer |
| GET | `/registrations` | List registrations; filters: `event_id`, `volunteer_id`, `project_id`, `transport_manifest_id`, `rsvp_status` | Any |
| GET | `/registrations/{registrationId}` | Get a registration | Any |
| POST | `/registrations/{registrationId}/confirm` | Confirm a registration — waiver and capacity gates; possible project auto-demotion | CommunityEngagementManager |
| POST | `/registrations/{registrationId}/cancel` | Cancel a registration (self or manager); frees the transport seat | CommunityEngagementManager, EmployeeVolunteer |
| POST | `/registrations/{registrationId}/check-in` | Day-of check-in; sets `checked_in_at` and `scheduled_hours_credit` | CommunityEngagementManager, StaffLead |
| POST | `/registrations/{registrationId}/sign-waiver` | Sign the current event waiver (`signer_name`, `signer_relation`, `media_consent`, optional `guardian_name`) | EmployeeVolunteer |
| POST | `/registrations/{registrationId}/verify-waiver` | Staff verifies a signed waiver (`WAIVER_SIGNED` → `WAIVER_VERIFIED`) | CommunityEngagementManager |
| POST | `/registrations/{registrationId}/assign-transport` | Assign the registration to a manifest seat (`transport_manifest_id`) | LogisticsCoordinator |
| POST | `/procurement-orders` | Create a supply/tool order (`event_id`, `project_id`, `lines`); computes the per-line-tax total; starts `DRAFT` | CommunityEngagementManager |
| GET | `/procurement-orders` | List orders; filters: `event_id`, `project_id`, `status` | Any |
| GET | `/procurement-orders/{orderId}` | Get an order | Any |
| POST | `/procurement-orders/{orderId}/submit` | Submit (or resubmit from `REJECTED`) an order; enters projected spend | CommunityEngagementManager |
| POST | `/procurement-orders/{orderId}/approve` | Approve an order — segregation of duties plus the budget gate | ProcurementOfficer |
| POST | `/procurement-orders/{orderId}/reject` | Reject an order (optional `rejection_reason`); segregation of duties | ProcurementOfficer |
| POST | `/procurement-orders/{orderId}/receive` | Mark an approved order received; drives `site_prep_complete` | CommunityEngagementManager |
| POST | `/procurement-orders/{orderId}/cancel` | Cancel a non-received order; budget reversal | CommunityEngagementManager |
| POST | `/vehicles` | Register a fleet vehicle (`name`, `seat_capacity`) | LogisticsCoordinator |
| GET | `/vehicles` | List vehicles | Any |
| POST | `/transport-manifests` | Book a vehicle window for an event (`event_id`, `vehicle_id`, `depart_at`, `return_at`, `cost_cents`); 30-minute turnaround conflict check | LogisticsCoordinator |
| GET | `/transport-manifests` | List manifests; filters: `event_id`, `vehicle_id`, `status` | Any |
| GET | `/transport-manifests/{manifestId}` | Get a manifest | Any |
| POST | `/transport-manifests/{manifestId}/confirm` | Confirm a booked manifest; cost enters committed spend | LogisticsCoordinator |
| POST | `/transport-manifests/{manifestId}/cancel` | Cancel a manifest; frees the window and unassigns its registrations | LogisticsCoordinator |
| POST | `/service-events/{eventId}/meal-plans` | Create the event's meal plan (`vendor_name`, `per_person_cost_cents`, optional `dietary_surcharge_cents`, `expected_event_version`; OCC; supersedes an existing `DRAFT` plan) | LogisticsCoordinator |
| GET | `/meal-plans` | List meal plans; filters: `event_id`, `vendor_name`, `status` | Any |
| GET | `/meal-plans/{mealPlanId}` | Get a meal plan | Any |
| POST | `/meal-plans/{mealPlanId}/order` | Place the meal order — 72-hour deadline, headcount snapshot, vendor-day capacity | LogisticsCoordinator |
| POST | `/meal-plans/{mealPlanId}/fulfill` | Mark the order fulfilled | LogisticsCoordinator |
| POST | `/meal-plans/{mealPlanId}/cancel` | Cancel a draft or ordered meal plan; spend reversal | LogisticsCoordinator |
| POST | `/supervision-assignments` | Assign a staff lead to a matched/locked project (`project_id`, `lead_volunteer_id`) | CommunityEngagementManager |
| GET | `/supervision-assignments` | List supervision assignments; filters: `project_id`, `event_id`, `lead_volunteer_id`, `status` | Any |
| GET | `/supervision-assignments/{assignmentId}` | Get a supervision assignment | Any |
| POST | `/supervision-assignments/{assignmentId}/withdraw` | Withdraw a supervision assignment (manager or the lead); possible project auto-demotion | CommunityEngagementManager, StaffLead |
| POST | `/sponsorships` | Pledge a sponsorship (`event_id`, `sponsor_name`, `match_type`, `rate_cents`, `pledge_cap_cents`); starts `PLEDGED` | FinanceController |
| GET | `/sponsorships` | List sponsorships; filters: `event_id`, `status` | Any |
| GET | `/sponsorships/{sponsorshipId}` | Get a sponsorship | Any |
| POST | `/sponsorships/{sponsorshipId}/commit` | Commit a pledge; provisional amount enters sponsorship credit | FinanceController |
| POST | `/sponsorships/{sponsorshipId}/settle` | Settle a committed sponsorship against actuals (event must be `COMPLETED`/`CLOSED`) | FinanceController |
| POST | `/sponsorships/{sponsorshipId}/withdraw` | Withdraw a pledge or commitment; credit reversal | FinanceController |
| POST | `/impact-records` | Nonprofit submits an impact record (`registration_id`, `project_id`, `hours_attended`, optional `photo_count`, `story_text`); starts `SUBMITTED` | NonprofitCoordinator |
| GET | `/impact-records` | List impact records; filters: `registration_id`, `project_id`, `event_id`, `status` | Any |
| GET | `/impact-records/{recordId}` | Get an impact record | Any |
| POST | `/impact-records/{recordId}/verify` | Verify a submitted record; verified-hours recompute | CommunityEngagementManager |
| POST | `/impact-records/{recordId}/publish` | Publish a verified record; media-consent gate | CommunityEngagementManager |
| POST | `/impact-records/{recordId}/reject` | Reject a record (optional `rejection_reason`); reverses hours if previously verified | CommunityEngagementManager |
| POST | `/impact-records/{recordId}/resubmit` | Nonprofit resubmits a rejected record; `rejection_reason` cleared | NonprofitCoordinator |
| POST | `/feedback-surveys` | Volunteer submits post-event feedback (`registration_id`, `rating`, `would_repeat`, optional `comments`); one per registration | EmployeeVolunteer |
| GET | `/feedback-surveys` | List feedback surveys; filters: `registration_id` | Any |
| GET | `/feedback-surveys/{surveyId}` | Get a feedback survey | Any |
| POST | `/_clock/set_current_utc` | Set the logical clock (`to_iso8601`); startup default is exactly 2026-08-01T00:00:00Z and the clock never falls back to wall-clock time | PlatformAdmin |

## 5. Error Code Catalogue

The trigger condition for each error is specified in the narratives of §2 and §3; this table enumerates identifiers and statuses only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_PROJECT_LEAD` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 403 Forbidden |
| `ERR_NONPROFIT_NOT_FOUND` | 404 Not Found |
| `ERR_PROJECT_NOT_FOUND` | 404 Not Found |
| `ERR_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_VOLUNTEER_NOT_FOUND` | 404 Not Found |
| `ERR_REGISTRATION_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_VEHICLE_NOT_FOUND` | 404 Not Found |
| `ERR_MANIFEST_NOT_FOUND` | 404 Not Found |
| `ERR_MEAL_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_SUPERVISION_NOT_FOUND` | 404 Not Found |
| `ERR_SPONSORSHIP_NOT_FOUND` | 404 Not Found |
| `ERR_IMPACT_RECORD_NOT_FOUND` | 404 Not Found |
| `ERR_SURVEY_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_EVENT_TRANSITION` | 409 Conflict |
| `ERR_INVALID_PROJECT_TRANSITION` | 409 Conflict |
| `ERR_INVALID_REGISTRATION_TRANSITION` | 409 Conflict |
| `ERR_INVALID_ORDER_TRANSITION` | 409 Conflict |
| `ERR_INVALID_MANIFEST_TRANSITION` | 409 Conflict |
| `ERR_INVALID_MEAL_PLAN_TRANSITION` | 409 Conflict |
| `ERR_INVALID_SPONSORSHIP_TRANSITION` | 409 Conflict |
| `ERR_INVALID_IMPACT_TRANSITION` | 409 Conflict |
| `ERR_INVALID_SUPERVISION_TRANSITION` | 409 Conflict |
| `ERR_EVENT_STATE_FORBIDS_WRITE` | 409 Conflict |
| `ERR_NONPROFIT_SUSPENDED` | 409 Conflict |
| `ERR_EVENT_NOT_READY` | 409 Conflict |
| `ERR_UNRESOLVED_SPONSORSHIPS` | 409 Conflict |
| `ERR_STALE_EVENT_VERSION` | 412 Precondition Failed |
| `ERR_WAIVER_NOT_SIGNED` | 409 Conflict |
| `ERR_WAIVER_NOT_VERIFIED` | 409 Conflict |
| `ERR_GUARDIAN_SIGNATURE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_MEDIA_CONSENT_MISSING` | 409 Conflict |
| `ERR_INSUFFICIENT_SUPERVISION` | 409 Conflict |
| `ERR_LEAD_NOT_QUALIFIED` | 409 Conflict |
| `ERR_EVENT_IN_PAST` | 422 Unprocessable Entity |
| `ERR_MEAL_ORDER_DEADLINE_PASSED` | 409 Conflict |
| `ERR_MANIFEST_IN_PAST` | 422 Unprocessable Entity |
| `ERR_VEHICLE_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_PROJECT_AT_CAPACITY` | 409 Conflict |
| `ERR_MANIFEST_FULL` | 409 Conflict |
| `ERR_VENDOR_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_ACTIVE_MEAL_PLAN_EXISTS` | 409 Conflict |
| `ERR_DUPLICATE_REGISTRATION` | 409 Conflict |
| `ERR_ACTIVE_SUPERVISION_EXISTS` | 409 Conflict |
| `ERR_ONE_SURVEY_PER_REGISTRATION` | 409 Conflict |
| `ERR_MIN_VOLUNTEERS_NOT_MET` | 409 Conflict |
| `ERR_SITE_PREP_INCOMPLETE` | 409 Conflict |
| `ERR_NO_MEAL_HEADCOUNT` | 409 Conflict |
| `ERR_DUPLICATE_EMAIL` | 409 Conflict |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
| `ERR_PROJECT_EVENT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_MANIFEST_EVENT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_IMPACT_PROJECT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_REGISTRATION_NOT_CHECKED_IN` | 409 Conflict |
| `ERR_SURVEY_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_REBOOK_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_BUDGET_WOULD_EXCEED` | 402 Payment Required |

# Meals On Wheels API — Product Requirements Document

## 1. Introduction

Community meal programs that serve homebound older adults juggle several concerns at once: they must screen new clients for nutritional and functional risk, honor the reporting obligations attached to Older Americans Act (OAA) funding, keep a fleet of volunteer drivers matched to geographic routes, and quietly watch for the day a client stops answering the door. This API is the system of record for one such program. It manages the full arc of participation — from the moment an intake coordinator first records an older adult's demographics, through nutritional assessment, standing meal-plan setup, day-by-day delivery, and the wellness-check-driven welfare-alert escalations that make home-delivered meals as much a safety-net as a food service.

The platform is deliberately organized around a small set of specialist operators who each own a slice of the workflow. Intake staff shepherd clients through enrollment and vacation holds; nutritionists own the clinical assessment; route managers build the delivery mesh and schedule meals; program administrators curate the volunteer roster; contribution clerks record the suggested (never mandatory) donations; and the volunteer drivers themselves close the loop by reporting what happened at each doorstep. Because a single delivery outcome can ripple outward — crediting funder-reportable meal units, resetting a no-answer counter, or opening a welfare alert — the system emphasizes consistent cascading side effects and careful reconciliation of computed totals over ad-hoc updates. This document specifies the entities, the lifecycle state machines, the calculation rules, and the endpoint and error contracts that together define correct behavior.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers that together establish the caller's identity and authority: `X-User-ID` and `X-User-Role`. The `X-User-ID` header names the acting user, and `X-User-Role` names the role under which they are acting. If either header is missing, or if `X-User-Role` does not name one of the roles defined below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly six roles, spelled precisely as follows:

- **`IntakeCoordinator`** — owns client intake, demographic and income updates, activation, discharge, and vacation holds, and shares the ability to resolve welfare alerts.
- **`Nutritionist`** — owns the creation and finalization of nutritional/functional assessments.
- **`RouteManager`** — owns routes, driver assignment and route activation, standing meal plans, delivery scheduling and delivery voiding, and welfare-alert escalation, and shares alert acknowledgement and resolution.
- **`ProgramAdmin`** — owns the volunteer-driver roster (registration and activation).
- **`ContributionClerk`** — records and voids donations.
- **`VolunteerDriver`** — records delivery outcomes on their own route and can acknowledge welfare alerts.

Five of these roles — `IntakeCoordinator`, `Nutritionist`, `RouteManager`, `ProgramAdmin`, and `ContributionClerk` — carry an **opaque** identity. For each of them, `X-User-ID` is an operator identifier that is not tied to any persisted entity; the server may record it where a workflow calls for it (for example, an alert acknowledgement stores the acknowledging operator's identifier in `acknowledged_by`) but never compares it against any entity's `id`. The sixth role, `VolunteerDriver`, is **entity-backed**: when `X-User-Role` is `VolunteerDriver`, `X-User-ID` is the `id` of the acting `VolunteerDriver` record. Ownership checks that gate delivery completion compare the delivery's route driver against this `X-User-ID` — specifically, a driver may complete a delivery only when their `X-User-ID` equals the `driver_id` of the route on which that delivery runs; otherwise the request is rejected with `ERR_NOT_ROUTE_DRIVER` (HTTP 403).

All six roles may perform every read (GET) operation. Write operations are restricted to the owning role(s) named above; where two roles share a write operation (alert acknowledgement is shared by `VolunteerDriver` and `RouteManager`; alert resolution is shared by `RouteManager` and `IntakeCoordinator`), both are authorized.

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

All list endpoints accept two pagination parameters, `limit` and `offset`. The `limit` parameter controls the maximum number of records returned in one page; it defaults to `10`, may be no smaller than `1`, and may be no larger than `100`. The `offset` parameter controls how many records to skip before the page begins; it defaults to `0` and may be no smaller than `0`. Any list result is ordered by `created_at` in ascending order (oldest first), so pagination is stable across successive pages.

For every list response, the `meta` block echoes the pagination context: `limit` and `offset` report the effective page window, `total_count` reports the total number of records matching the query before paging, and `has_more` is a boolean that is true exactly when records remain beyond the current page.

### 2.4. Common Resource Properties, Identifiers, and Versioning

Every persisted resource is assigned a server-minted `id`, formatted as a UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC value with three fractional digits. Most resources additionally carry an `updated_at` timestamp (same format) and an integer `version` that begins at 1 on creation and increases by exactly 1 on every mutation that changes the resource; `updated_at` is refreshed to the mutation time whenever `version` advances. The entities that carry `updated_at` and `version` are `Client`, `Assessment`, `MealPlan`, `Route`, `VolunteerDriver`, `Delivery`, `WelfareAlert`, `Contribution`, and `VacationHold`.

The one exception is the `WellnessCheck` resource, which is an immutable event record: it carries only `id` and `created_at`. It has neither an `updated_at` field nor a `version` field, because once written it is never mutated.

### 2.5. Optimistic Concurrency Control on Client Mutations

Two write operations against a client are guarded by optimistic concurrency control (OCC) so that a caller never overwrites state it has not observed: updating a client's demographics/income and creating a standing meal plan for a client. Both require the caller to submit an `expected_client_version` field carrying the `version` of the `Client` the caller last read.

Creating a standing meal plan for a client is the OCC-critical case. A new plan legitimately supersedes (and cancels) the client's prior active plan, so allowing a create built on a stale view of the client would silently discard a plan the writer never saw. Accordingly, when a meal-plan creation is requested, the submitted `expected_client_version` must equal the target `Client`'s current `version`; if another writer has advanced the client's `version` since the caller last read it, the create is rejected with `ERR_STALE_CLIENT_VERSION` (HTTP 412). The demographics/income update applies the same rule: its `expected_client_version` must match the client's current `version`, and a mismatch is likewise rejected with `ERR_STALE_CLIENT_VERSION` (HTTP 412). No other endpoint takes a version field.

### 2.6. Monetary and Unit Precision

Money is handled in integer cents throughout; there is no floating-point currency. The only rounding in the system occurs when deriving the per-meal suggested contribution: that single per-meal figure is rounded to a whole number of cents using round-half-up (a value exactly halfway between two cents rounds up to the larger cent). All monthly and aggregate money totals are then formed as exact integer products or sums of already-rounded per-meal figures and recorded amounts — they are never re-rounded. Meal counts, OAA unit counts, and age in years are whole integers; age in years is computed by taking the floor (rounding down to the nearest whole year).

### 2.7. Cascading Consistency and Nested Resource Resolution

Many operations in this system mutate more than one resource. Whenever a parent transition cascades into a child (for example, a client going on hold suspending its meal plan, or a plan cancellation cancelling its scheduled deliveries), each affected resource undergoes its own state transition, has its own `version` incremented by 1, and has its own `updated_at` refreshed. The detailed cascade sets are specified per-workflow in §3; the invariant here is that cascades are applied completely and consistently, never partially.

Endpoints whose URL nests one resource inside another validate path-referenced resources left to right. For a path that names a client and then a sub-resource, the client is resolved first; if it does not exist the request fails with `ERR_CLIENT_NOT_FOUND` (HTTP 404) before any deeper resource is considered. Each resource type returns its own not-found error when the referenced resource is absent: `ERR_CLIENT_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_MEAL_PLAN_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`, `ERR_DRIVER_NOT_FOUND`, `ERR_DELIVERY_NOT_FOUND`, `ERR_WELLNESS_CHECK_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, `ERR_CONTRIBUTION_NOT_FOUND`, and `ERR_HOLD_NOT_FOUND` (all HTTP 404). Foreign keys referenced in a request body — for example the `assessment_id`, `route_id`, `meal_plan_id`, `driver_id`, or `client_id` a body may carry — are likewise checked for existence and yield the corresponding resource-specific not-found error.

### 2.8. Request Validation Order and Error Precedence

When several conditions could reject a request, they are evaluated in a fixed order so that the returned error is deterministic. The ordering is: (1) authentication — the `X-User-ID` and `X-User-Role` headers are present and the role is known, else `ERR_UNAUTHENTICATED`; (2) authorization — the acting role may call this endpoint, else `ERR_UNAUTHORIZED`; (3) the delivery-completion route-ownership check, where the acting driver must own the route, else `ERR_NOT_ROUTE_DRIVER`; (4) request shape — all required fields present with correct primitive types, else `ERR_INVALID_REQUEST` (HTTP 400); (5) field values in range and valid enum members, else `ERR_INVALID_FIELD_VALUE` (HTTP 422); (6) existence of path-referenced resources, checked left to right, returning the resource-specific not-found error; (7) existence of body-referenced foreign keys, returning the resource-specific not-found error; (8) referential consistency between referenced resources; (9) state preconditions on the target and referenced resources; (10) cross-entity state preconditions; (11) domain safety checks such as therapeutic-diet matching; (12) temporal and scheduling checks such as delivery-day membership, hold overlap, and driver-day conflict; (13) other business constraints such as zone matching and route capacity; and finally (14) the optimistic-concurrency version check. Lower-numbered checks always take precedence, so a request that violates several rules surfaces the earliest-ordered failure.

State-precondition failures (check 9) share a generic umbrella meaning, `ERR_INVALID_STATE` (HTTP 409), but each transition endpoint returns the resource-specific alias for its own precondition where one is defined: finalizing a non-draft assessment returns `ERR_ASSESSMENT_NOT_DRAFT`, completing a delivery that is not scheduled returns `ERR_DELIVERY_NOT_SCHEDULED`, voiding a delivery that is not delivered returns `ERR_DELIVERY_NOT_DELIVERED`, ending a hold that is not active returns `ERR_HOLD_NOT_ACTIVE`, an invalid welfare-alert transition returns `ERR_ALERT_INVALID_STATE`, and activating a driver that is not pending returns `ERR_DRIVER_NOT_PENDING` — each carrying HTTP 409.

Field-shape and range validation (checks 4 and 5) apply to every write endpoint. A missing required field or a value of the wrong primitive type yields `ERR_INVALID_REQUEST`. A value that is present and correctly typed but out of its allowed range or not a valid enum member yields `ERR_INVALID_FIELD_VALUE`; this covers a household size below 1, a contribution amount that is not strictly positive, an ADL score outside 0 through 6, a DETERMINE point total outside 0 through 21, a recommended or per-day meal count outside 1 through 3, an end date earlier than its start date, an empty set of delivery days or service days, and a birth date that is not strictly earlier than the present.

## 3. Business Logic & Workflows

### 3.1. Client Intake and Eligibility Determination

Intake begins when an `IntakeCoordinator` records a new older adult. The intake payload carries the client's `full_name`, `birth_date` (an ISO 8601 date of birth), `household_size`, self-reported gross `monthly_income_cents`, the delivery `address_zone` code (for example, `Z1`), and a contact `phone`. The `birth_date` must be strictly earlier than the moment of creation, `household_size` must be at least 1, and `monthly_income_cents` must be zero or greater. A freshly intake'd client enters the lifecycle in `INTAKE` status; its `enrollment_status` will move through `ASSESSED`, `ACTIVE`, `ON_HOLD`, and finally `DISCHARGED` as the workflows below unfold.

Two determinations are computed at intake and stored on the client. The first is Older Americans Act age eligibility, recorded on `oaa_eligible`: the client's age in whole years is the number of days between the birth date and the creation date divided by 365.2425 and then rounded down to a whole year, and `oaa_eligible` is true exactly when that age in years is at least 60. The second is the contribution `income_tier`, which places the household on a sliding scale against the federal poverty line. The applicable monthly poverty figure in cents is 1,255.00 dollars for a one-person household plus an additional 440.00 dollars for each additional household member — that is, a base of 125,500 cents plus 44,000 cents times one less than the household size. The income ratio is the client's `monthly_income_cents` divided by that poverty figure, compared exactly without rounding. If the ratio is at or below 1.00 the client is `TIER_A`; otherwise if it is at or below 1.85 the client is `TIER_B`; otherwise the client is `TIER_C`. Both upper boundaries are inclusive.

A client also carries several computed roll-up fields that begin at zero and are maintained by later activity: `suggested_contribution_cents` (the monthly suggested donation), `donation_balance_cents` (the reconciled sum of recorded donations), `lifetime_oaa_units` (the reconciled count of delivered OAA meal units), and `consecutive_no_answer` (a running count of back-to-back no-answer deliveries). These are discussed where the activity that drives them is described.

An `IntakeCoordinator` may later update a client's demographics and income. That update is optimistic-concurrency-guarded (see §2.5) and accepts any of `household_size`, `monthly_income_cents`, `address_zone`, and `phone`, together with the required `expected_client_version`. Whenever `monthly_income_cents` or `household_size` changes, the `income_tier` is recomputed by the same poverty-line rule described above, and because the tier drives pricing, the client's suggested contribution is re-derived from the new tier — the reconciled figure replacing the one computed at intake, with the difference between them being the reconciliation delta.

Once a client has an active standing plan, an `IntakeCoordinator` moves it from `ASSESSED` to `ACTIVE` by enrolling it into active service. This activation is permitted only when the client is currently in `ASSESSED` status — any other status yields `ERR_CLIENT_NOT_ASSESSED` (HTTP 409) — and only when the client has exactly one meal plan in `ACTIVE` status — a client whose count of `ACTIVE` meal plans is not exactly one (zero, or more than one) is rejected with the generic `ERR_INVALID_STATE` (HTTP 409); it advances the client to `ACTIVE` and increments the client's `version` by 1.

A read-only client roll-up is also available. It reports the client's `income_tier`, `oaa_eligible` flag, current monthly `suggested_contribution_cents`, reconciled `donation_balance_cents`, the `provisioned_monthly_units` and `delivered_units` OAA figures, and the `lifetime_oaa_units` total. The two OAA figures are defined in §3.5 and §3.8; the suggested-contribution and donation figures in §3.4 and §3.8.

### 3.2. Nutritional and Functional Assessment

A `Nutritionist` performs the clinical screening. Creating an assessment for a client records the DETERMINE checklist total in `nutrition_determine_points` (0 through 21), a functional score in `adl_score` counting the Activities of Daily Living that require help (0 through 6), a `recommended_meals_per_day` count (1 through 3), and two therapeutic-diet inputs: `therapeutic_diet_required`, a boolean that defaults to false, and `therapeutic_diet_type`, which defaults to `NONE` and is otherwise one of `RENAL`, `DIABETIC`, `LOW_SODIUM`, or `PUREED`. Each assessment records the assessed client's identifier in `client_id`. A newly created assessment starts in `DRAFT` status.

Two bands are computed and stored on the assessment at creation. The nutritional risk band, `nutrition_risk_category`, is `HIGH` when `nutrition_determine_points` is at least 6, `MODERATE` when it is at least 3 but below 6 (so a total of 5 is `MODERATE` and `HIGH` begins exactly at 6), and `GOOD` otherwise. The functional band, `functional_level`, is `DEPENDENT` when `adl_score` is at least 5, `PARTIAL` when it is at least 2 but below 5, and `INDEPENDENT` otherwise.

Finalizing a draft assessment advances it from `DRAFT` to `FINALIZED`; finalization is allowed only from `DRAFT`, and attempting it on any other status yields `ERR_ASSESSMENT_NOT_DRAFT` (HTTP 409). Finalization carries two cascades. First, any prior assessment for the same client that was already `FINALIZED` is moved to `SUPERSEDED` (its own `version` incrementing), so a client has at most one finalized assessment at a time. Second, if the client was still in `INTAKE` status, finalizing this first assessment advances the client from `INTAKE` to `ASSESSED` and increments the client's `version`. The assessment's own `version` is incremented by 1 on finalization. A client's assessments can be listed and filtered by `status`.

### 3.3. Routes, Volunteer Drivers, and Assignment

A `RouteManager` builds the delivery mesh. Creating a route records its `name`, the delivery `zone` it covers, the non-empty set of `service_days` on which it runs (each a weekday among `MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT`, `SUN`), and `max_meals_per_run`, the per-date capacity ceiling (at least 1) that caps the total meals of the scheduled deliveries assigned to the route on any single date. A route is created in `DRAFT` status with no driver; its `driver_id` is null until a driver is assigned. Routes may be listed and filtered by `driver_id`, `zone`, and `status`.

Separately, a `ProgramAdmin` curates the volunteer roster. Registering a volunteer driver records the driver's `full_name` and `phone` and creates the record in `PENDING` status. Activating a pending driver advances it from `PENDING` to `ACTIVE`; activation is allowed only from `PENDING`, and any other status yields `ERR_DRIVER_NOT_PENDING` (HTTP 409). The `version` of the driver increments by 1 on activation. Drivers may be listed and filtered by `status`.

Assigning a driver to a route sets the route's `driver_id` to the supplied `driver_id` and increments the route's `version`. Assignment enforces a driver-day exclusivity rule: the driver may not already be assigned to another route — one in either `DRAFT` or `ACTIVE` status — whose `service_days` share at least one weekday with this route's `service_days`. If such an overlap exists, the assignment is rejected with `ERR_DRIVER_DAY_CONFLICT` (HTTP 409).

Activating a route advances it from `DRAFT` to `ACTIVE` and increments the route's `version`. Activation has two preconditions evaluated in order: the route must have a driver assigned, and that assigned driver must itself be `ACTIVE`. A route with no assigned driver is rejected with `ERR_ROUTE_HAS_NO_DRIVER` (HTTP 409); a route whose assigned driver is not yet `ACTIVE` is rejected with `ERR_DRIVER_NOT_ACTIVE` (HTTP 409). Only an `ACTIVE` route may serve a meal plan, so this activation gate is what admits a route into service.

### 3.4. Standing Meal Plans and Suggested-Contribution Pricing

A standing meal plan is the recurring order that generates deliveries. A `RouteManager` creates a plan for a client, and the create is optimistic-concurrency-guarded on the client (see §2.5): the payload names the source `assessment_id`, the serving `route_id`, the `meal_type` (one of `FROZEN`, `HOT`, or `THERAPEUTIC`), an optional `therapeutic_diet_type` (defaulting to `NONE`), the `meals_per_day` count (1 through 3), the non-empty set of `delivery_days` (weekdays drawn from `MON` through `SUN`), and the `expected_client_version`. A new plan is created in `ACTIVE` status.

Creating a plan is subject to a chain of consistency checks, evaluated in the precedence order of §2.8. The referenced `assessment_id` must belong to the same client named in the path, else `ERR_ASSESSMENT_CLIENT_MISMATCH` (HTTP 422). The referenced assessment must be `FINALIZED`, else `ERR_ASSESSMENT_NOT_FINALIZED` (HTTP 409). The referenced route must be `ACTIVE`, else `ERR_ROUTE_NOT_ACTIVE` (HTTP 409). The client must be enrolled — its `enrollment_status` must be either `ASSESSED` or `ACTIVE` — else `ERR_CLIENT_NOT_ASSESSED` (HTTP 409). When the plan's `meal_type` is `THERAPEUTIC`, the referenced assessment must have `therapeutic_diet_required` set to true and its `therapeutic_diet_type` must equal the plan's `therapeutic_diet_type`; a mismatch on either yields `ERR_THERAPEUTIC_DIET_MISMATCH` (HTTP 422). The route's `zone` must equal the client's `address_zone`, else `ERR_ROUTE_ZONE_MISMATCH` (HTTP 422). Finally the OCC check applies: `expected_client_version` must equal the client's current `version`, else `ERR_STALE_CLIENT_VERSION` (HTTP 412).

Because a client may hold only one standing order at a time, creating a new plan supersedes the client's prior `ACTIVE` plan: that prior plan moves from `ACTIVE` to `CANCELLED`, every one of its `SCHEDULED` deliveries is cancelled in turn, and the client's `version` is incremented by 1. This supersession is exactly why the create is version-guarded — a stale client view could cancel a plan the writer never observed.

Two figures are computed and stored on the plan at creation. The provisioned `weekly_meal_count` depends on the modality. For a `FROZEN` plan, meals arrive in a single weekly bulk run covering a full seven-day week, so the weekly count is `meals_per_day` multiplied by 7, capped at a maximum of 21 meals per week. For a `HOT` or `THERAPEUTIC` plan, fresh meals arrive only on each service day, so the weekly count is `meals_per_day` multiplied by the number of `delivery_days`, again capped at 21. The cap of 21 is applied after the multiplication.

The plan also stores `suggested_contribution_per_meal_cents`, the per-meal suggested (never mandatory) donation. It is the base meal cost of 725 cents multiplied by the tier factor for the client's `income_tier` — 0.15 for `TIER_A`, 0.35 for `TIER_B`, and 0.55 for `TIER_C` — with that single product rounded half-up to a whole number of cents. This per-meal rounding happens first and is pinned; the monthly figure is built from the already-rounded per-meal value. The client-level monthly `suggested_contribution_cents` is that rounded per-meal amount multiplied by the projected monthly meals, where projected monthly meals is the active plan's `weekly_meal_count` multiplied by 4 weeks per month. This monthly product is exact — it is never re-rounded. If a client has no `ACTIVE` plan, the monthly `suggested_contribution_cents` is 0. The value computed from the tier at intake is the provisional figure; after a demographics/income update changes the tier (see §3.1), the per-meal and monthly figures are recomputed from the new tier, and that recomputation is the reconciliation of the provisional estimate.

A `RouteManager` may cancel an active plan directly. Cancellation is allowed only when the plan is `ACTIVE`, otherwise `ERR_MEAL_PLAN_NOT_ACTIVE` (HTTP 409); it moves the plan from `ACTIVE` to `CANCELLED`, cancels every one of the plan's `SCHEDULED` deliveries as a cascade, and increments the plan's `version` by 1. Meal plans may be read individually and listed or filtered by `client_id`, `assessment_id`, `route_id`, and `status`.

### 3.5. Scheduling and Completing Deliveries

A `RouteManager` schedules deliveries against a standing plan. A scheduling request names the `meal_plan_id` and the `scheduled_date` (an ISO 8601 date). At creation the delivery copies `client_id`, `route_id`, and `meal_type` from the plan, so those fields need not be supplied. A new delivery starts in `SCHEDULED` status, and its `oaa_units_accrued` and `delivered_at` fields begin at 0 and null respectively.

Scheduling has several guards. The client must be `ACTIVE`, else `ERR_CLIENT_NOT_ACTIVE` (HTTP 409). The referenced plan must be `ACTIVE`, else `ERR_MEAL_PLAN_NOT_ACTIVE` (HTTP 409). The weekday of `scheduled_date` must be one of the plan's `delivery_days`, else `ERR_DELIVERY_DAY_MISMATCH` (HTTP 422). And the route's per-date capacity must not be exceeded: the sum of `meal_count` over the existing `SCHEDULED` deliveries already on that route for that same `scheduled_date`, plus this delivery's own `meal_count`, must not exceed the route's `max_meals_per_run`; if it would, the request is rejected with `ERR_ROUTE_CAPACITY_EXCEEDED` (HTTP 409).

The delivery's `meal_count` is computed from the plan's modality. For a `FROZEN` plan, the single weekly bulk run carries the whole week's meals, so the delivery's `meal_count` equals the plan's `weekly_meal_count`. For a `HOT` or `THERAPEUTIC` plan, each service-day delivery carries that day's meals, so the delivery's `meal_count` equals the plan's `meals_per_day`.

Recording a delivery outcome is the volunteer driver's job, and it is the entity-backed ownership point of the system: the acting `VolunteerDriver` may complete a delivery only when their `X-User-ID` equals the `driver_id` of the delivery's route, else `ERR_NOT_ROUTE_DRIVER` (HTTP 403). The completion payload carries an `outcome` — one of `DELIVERED`, `NO_ANSWER`, or `SKIPPED` — and optional `wellness_notes` free text. Completion is allowed only from `SCHEDULED`; any other status yields `ERR_DELIVERY_NOT_SCHEDULED` (HTTP 409). The three outcomes diverge sharply:

- **`DELIVERED`**: the delivery moves `SCHEDULED → DELIVERED`; `oaa_units_accrued` is set to the delivery's `meal_count`; `delivered_at` is stamped with the completion time; the delivery's `meal_count` is added to the client's `lifetime_oaa_units` as a ledger-sync cascade; the client's `consecutive_no_answer` is reset to 0; and a `WellnessCheck` is created for this delivery and client with `outcome` `OK`. The delivery's `version` and the client's `version` each increment by 1.
- **`NO_ANSWER`**: the delivery moves `SCHEDULED → NO_ANSWER`, and a three-hop cascade fires. First, a `WellnessCheck` is created for this delivery and client with `outcome` `NO_ANSWER`. Second, that check increments the client's `consecutive_no_answer` by 1. Third, that check opens a `WelfareAlert` referencing it, whose severity is derived as described in §3.6. The delivery's `version` and the client's `version` each increment by 1. No OAA units accrue.
- **`SKIPPED`**: the delivery moves `SCHEDULED → SKIPPED`; no OAA units accrue and the client's `consecutive_no_answer` is left unchanged. Only the delivery's `version` increments by 1.

When a wellness check is created as part of completion, its `delivery_id` and `client_id` are copied from the delivery, its `outcome` is set as above, and any supplied `wellness_notes` are stored in the check's `notes` field. Wellness checks may be read individually and listed or filtered by `delivery_id`, `client_id`, and `outcome`.

A `RouteManager` may void a delivery that was already `DELIVERED` — a compensating action, for instance when a delivery was recorded in error. Voiding is allowed only from `DELIVERED`, else `ERR_DELIVERY_NOT_DELIVERED` (HTTP 409). It moves the delivery `DELIVERED → VOIDED`, subtracts the delivery's `meal_count` back out of the client's `lifetime_oaa_units` as a ledger-sync compensation, resets the delivery's `oaa_units_accrued` to 0, and increments the delivery's `version` and the client's `version` each by 1. Deliveries may be read individually and listed or filtered by `meal_plan_id`, `client_id`, `route_id`, `status`, and `scheduled_date`.

The OAA reporting figures follow from all of this. The **provisioned** monthly units, reported as `provisioned_monthly_units` on the client roll-up, are the client's `ACTIVE` plan `weekly_meal_count` multiplied by 4 weeks per month — a planning figure independent of what was actually delivered. The **delivered** units, reported as `delivered_units`, are the sum of `meal_count` over the client's deliveries whose status is `DELIVERED`; deliveries that are `SKIPPED`, `NO_ANSWER`, `CANCELLED`, or `VOIDED` are excluded, which is exactly why delivered units diverge from provisioned units whenever a delivery falls short. The live `lifetime_oaa_units` ledger on the client is the running reconciliation of that same delivered figure, maintained forward on each `DELIVERED` completion and backward on each void.

### 3.6. Wellness Checks and Welfare-Alert Escalation

A no-answer delivery is a welfare signal, and the escalation chain in §3.5 opens a `WelfareAlert`. The alert records the at-risk client in `client_id` and the identifier of the no-answer check that opened it in `triggering_wellness_check_id`, both copied from the triggering event. Its `severity` is derived from the client's `consecutive_no_answer` counter as it stands after that no-answer event has incremented it: the alert is `HIGH` when the counter is at least 2 — meaning the second consecutive no-answer already yields `HIGH` — and `LOW` otherwise. A new alert opens in `OPEN` status.

Alerts move through an acknowledgement-and-escalation lifecycle. A `VolunteerDriver` or a `RouteManager` may acknowledge an `OPEN` alert, moving it `OPEN → ACKNOWLEDGED` and recording the acting operator's identifier in `acknowledged_by`. A `RouteManager` may escalate an alert that is either `OPEN` or `ACKNOWLEDGED`, moving it to `ESCALATED` (so both `OPEN → ESCALATED` and `ACKNOWLEDGED → ESCALATED` are valid). An alert is resolved by a `RouteManager` or an `IntakeCoordinator` from either `ACKNOWLEDGED` or `ESCALATED`, moving it to `RESOLVED` (both `ACKNOWLEDGED → RESOLVED` and `ESCALATED → RESOLVED` are valid). Each of these transitions increments the alert's `version` by 1. Any alert transition attempted from a state that does not permit it — for example acknowledging an alert that is not `OPEN`, escalating one that is neither `OPEN` nor `ACKNOWLEDGED`, or resolving one that is neither `ACKNOWLEDGED` nor `ESCALATED` — is rejected with `ERR_ALERT_INVALID_STATE` (HTTP 409). Alerts may be read individually and listed or filtered by `client_id`, `triggering_wellness_check_id`, `status`, and `severity`.

### 3.7. Vacation Holds and Service Suspension

When a client travels or is temporarily hospitalized, an `IntakeCoordinator` places a vacation hold to pause service without discharging. A hold records the `client_id`, an inclusive `start_date`, and an inclusive `end_date`, where the end date must be on or after the start date. Placing a hold requires the client to be `ACTIVE`, else `ERR_CLIENT_NOT_ACTIVE` (HTTP 409). It also requires that no other hold for the client overlap the requested window: any existing hold for the client whose status is `ACTIVE` or `COMPLETED` counts, cancelled holds are ignored, and two windows overlap — including when they merely touch at an endpoint — exactly when the new start is on or before the existing end and the existing start is on or before the new end. An overlap yields `ERR_HOLD_OVERLAP` (HTTP 409). A new hold is created in `ACTIVE` status.

Placing a hold cascades through the client's active service. The client moves `ACTIVE → ON_HOLD`; the client's `ACTIVE` meal plan moves `ACTIVE → SUSPENDED`; every one of that plan's `SCHEDULED` deliveries whose `scheduled_date` falls within the hold window (from `start_date` through `end_date`, inclusive) moves `SCHEDULED → CANCELLED`; and the client's `version` is incremented by 1, with the plan and each cancelled delivery incrementing their own `version` as well.

Ending a hold reverses the suspension. An `IntakeCoordinator` ends an `ACTIVE` hold; ending is allowed only from `ACTIVE`, else `ERR_HOLD_NOT_ACTIVE` (HTTP 409). The hold moves `ACTIVE → COMPLETED`, and provided the client has no other still-`ACTIVE` hold, the client moves `ON_HOLD → ACTIVE`, which in turn resumes the client's `SUSPENDED` meal plan by moving it `SUSPENDED → ACTIVE`. The hold's `version` increments by 1, and the client and resumed plan each increment their own `version`. (Deliveries cancelled during the hold are not automatically recreated; resumption restores the standing plan only.) Vacation holds may be read individually and listed or filtered by `client_id` and `status`.

### 3.8. Contributions, Donations, and Reconciliation

Suggested contributions are never mandatory, but many clients choose to donate. A `ContributionClerk` records a donation for a client, capturing the `amount_cents` (which must be strictly greater than 0) and the attribution `period_month` in `YYYY-MM` format. A recorded donation is created in `RECORDED` status; recording it adds its `amount_cents` to the client's `donation_balance_cents` and increments the client's `version` by 1.

A `ContributionClerk` may void a recorded donation as a compensating action. Voiding is allowed only from `RECORDED` — voiding a contribution in any other status is rejected with the generic `ERR_INVALID_STATE` (HTTP 409); it moves the contribution `RECORDED → VOIDED`, subtracts its `amount_cents` back out of the client's `donation_balance_cents`, and increments the contribution's `version` and the client's `version` each by 1. The authoritative `donation_balance_cents` is always the reconciled sum of `amount_cents` over the client's contributions whose status is `RECORDED`; voided contributions are never counted. Contributions may be read individually and listed or filtered by `client_id`, `status`, and `period_month`.

### 3.9. Client Discharge and Terminal Cascades

Discharge is the terminal step of the client lifecycle, performed by an `IntakeCoordinator`. A client may be discharged from `ASSESSED`, `ACTIVE`, or `ON_HOLD` status — a discharge attempted from any other status (for example an `INTAKE` or already-`DISCHARGED` client) is rejected with the generic `ERR_INVALID_STATE` (HTTP 409) — and discharge moves the client to `DISCHARGED`, a terminal state. Discharge is a broad cascade that tears down the client's active service in one operation: the client's meal plan, if it is currently `ACTIVE` or `SUSPENDED`, moves to `CANCELLED`; every `SCHEDULED` delivery belonging to the client moves to `CANCELLED`; and every still-`ACTIVE` vacation hold for the client moves to `CANCELLED`. The client's `version` is incremented by 1, and every entity swept by the cascade increments its own `version` as part of the same operation.

## 4. Endpoint Definitions

The endpoints below constitute the full API surface. Endpoints that create a new resource return HTTP 201; endpoints that read or modify an existing resource return HTTP 200. All request and response bodies, side effects, and validation semantics are as described in the §2 and §3 narratives above; the table records only the routing contract. Every GET endpoint is available to all six roles.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/clients` | Intake a new client (starts INTAKE) | `IntakeCoordinator` |
| GET | `/clients/{id}` | Read a client | All roles |
| PATCH | `/clients/{id}` | Update client demographics/income; recomputes income tier (OCC-guarded) | `IntakeCoordinator` |
| POST | `/clients/{id}/activate` | Enroll an assessed client into active service | `IntakeCoordinator` |
| POST | `/clients/{id}/discharge` | Discharge a client; cascades to plan, deliveries, holds | `IntakeCoordinator` |
| GET | `/clients/{id}/summary` | Computed client roll-up (contribution, OAA units, tier) | All roles |
| POST | `/clients/{id}/assessments` | Create a DRAFT nutritional/functional assessment | `Nutritionist` |
| GET | `/clients/{id}/assessments` | List a client's assessments | All roles |
| POST | `/assessments/{id}/finalize` | Finalize a DRAFT assessment; supersedes prior; may advance client | `Nutritionist` |
| POST | `/clients/{id}/meal-plans` | Create an ACTIVE standing meal plan (OCC-guarded on client) | `RouteManager` |
| GET | `/meal-plans/{id}` | Read a meal plan | All roles |
| GET | `/meal-plans` | List/filter meal plans | All roles |
| POST | `/meal-plans/{id}/cancel` | Cancel an ACTIVE meal plan | `RouteManager` |
| POST | `/routes` | Create a delivery route (DRAFT, no driver) | `RouteManager` |
| GET | `/routes/{id}` | Read a route | All roles |
| GET | `/routes` | List/filter routes | All roles |
| POST | `/routes/{id}/assign-driver` | Assign a volunteer driver to a route | `RouteManager` |
| POST | `/routes/{id}/activate` | Activate a route (requires an ACTIVE assigned driver) | `RouteManager` |
| POST | `/drivers` | Register a volunteer driver (PENDING) | `ProgramAdmin` |
| GET | `/drivers` | List/filter volunteer drivers | All roles |
| POST | `/drivers/{id}/activate` | Activate a PENDING volunteer driver | `ProgramAdmin` |
| POST | `/deliveries` | Schedule a delivery for a meal plan on a date | `RouteManager` |
| GET | `/deliveries/{id}` | Read a delivery | All roles |
| GET | `/deliveries` | List/filter deliveries | All roles |
| POST | `/deliveries/{id}/complete` | Record delivery outcome; driver must own the route | `VolunteerDriver` |
| POST | `/deliveries/{id}/void` | Void a DELIVERED delivery (compensating action) | `RouteManager` |
| GET | `/wellness-checks/{id}` | Read a wellness check | All roles |
| GET | `/wellness-checks` | List/filter wellness checks | All roles |
| GET | `/welfare-alerts/{id}` | Read a welfare alert | All roles |
| GET | `/welfare-alerts` | List/filter welfare alerts | All roles |
| POST | `/welfare-alerts/{id}/acknowledge` | Acknowledge an OPEN welfare alert | `VolunteerDriver`, `RouteManager` |
| POST | `/welfare-alerts/{id}/escalate` | Escalate an OPEN or ACKNOWLEDGED welfare alert | `RouteManager` |
| POST | `/welfare-alerts/{id}/resolve` | Resolve an ACKNOWLEDGED or ESCALATED welfare alert | `RouteManager`, `IntakeCoordinator` |
| POST | `/clients/{id}/contributions` | Record a donation for a client | `ContributionClerk` |
| GET | `/contributions/{id}` | Read a contribution | All roles |
| GET | `/contributions` | List/filter contributions | All roles |
| POST | `/contributions/{id}/void` | Void a RECORDED contribution (compensating action) | `ContributionClerk` |
| POST | `/clients/{id}/vacation-holds` | Place an ACTIVE vacation hold on a client | `IntakeCoordinator` |
| GET | `/vacation-holds/{id}` | Read a vacation hold | All roles |
| GET | `/vacation-holds` | List/filter vacation holds | All roles |
| POST | `/vacation-holds/{id}/end` | End an ACTIVE vacation hold (resumes the plan) | `IntakeCoordinator` |

## 5. Error Code Catalogue

The trigger conditions for each error are described in the §2 and §3 narratives; this table records the machine-readable identifier and its HTTP status.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_ROUTE_DRIVER` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_FIELD_VALUE` | 422 |
| `ERR_CLIENT_NOT_FOUND` | 404 |
| `ERR_ASSESSMENT_NOT_FOUND` | 404 |
| `ERR_MEAL_PLAN_NOT_FOUND` | 404 |
| `ERR_ROUTE_NOT_FOUND` | 404 |
| `ERR_DRIVER_NOT_FOUND` | 404 |
| `ERR_DELIVERY_NOT_FOUND` | 404 |
| `ERR_WELLNESS_CHECK_NOT_FOUND` | 404 |
| `ERR_ALERT_NOT_FOUND` | 404 |
| `ERR_CONTRIBUTION_NOT_FOUND` | 404 |
| `ERR_HOLD_NOT_FOUND` | 404 |
| `ERR_ASSESSMENT_CLIENT_MISMATCH` | 422 |
| `ERR_ASSESSMENT_NOT_FINALIZED` | 409 |
| `ERR_ROUTE_NOT_ACTIVE` | 409 |
| `ERR_CLIENT_NOT_ASSESSED` | 409 |
| `ERR_CLIENT_NOT_ACTIVE` | 409 |
| `ERR_MEAL_PLAN_NOT_ACTIVE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ASSESSMENT_NOT_DRAFT` | 409 |
| `ERR_DELIVERY_NOT_SCHEDULED` | 409 |
| `ERR_DELIVERY_NOT_DELIVERED` | 409 |
| `ERR_HOLD_NOT_ACTIVE` | 409 |
| `ERR_ALERT_INVALID_STATE` | 409 |
| `ERR_DRIVER_NOT_PENDING` | 409 |
| `ERR_ROUTE_HAS_NO_DRIVER` | 409 |
| `ERR_DRIVER_NOT_ACTIVE` | 409 |
| `ERR_THERAPEUTIC_DIET_MISMATCH` | 422 |
| `ERR_DELIVERY_DAY_MISMATCH` | 422 |
| `ERR_HOLD_OVERLAP` | 409 |
| `ERR_DRIVER_DAY_CONFLICT` | 409 |
| `ERR_ROUTE_ZONE_MISMATCH` | 422 |
| `ERR_ROUTE_CAPACITY_EXCEEDED` | 409 |
| `ERR_STALE_CLIENT_VERSION` | 412 |

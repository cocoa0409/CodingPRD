# Mobile Pet Grooming API — Product Requirements Document

## 1. Introduction

This document specifies the backend service for a mobile pet-grooming operation — a fleet of equipped vans that travel to customers' homes to bathe, trim, and style their pets. Unlike a fixed-salon booking tool, the platform must reason about geography (which van covers which neighborhood), time (each van runs a bounded daily service window broken into back-to-back stops with travel buffers between them), and safety (a dog that has lapsed on its rabies shot, or one flagged as aggressive, cannot simply be slotted in). The pricing is genuinely two-faced: a customer is quoted a forward-looking estimate when they book, but the bill they actually pay is reconciled at the van door based on what the groomer was able to deliver.

The service coordinates five human and operational actors. Pet owners register themselves and their animals, upload vaccination proof, request appointments, and pause or cancel recurring grooming plans. Dispatchers run the day-to-day operation: they price appointments, fit them onto a van's route, assign a qualified groomer, and record no-shows. Groomers work in the field, completing the appointments routed to them. A platform administrator owns the service catalog — breeds, service tiers, add-ons, vans, and groomers — and holds the authority to waive fees and drive the server's logical clock for testing. The system enforces a strict separation between what was promised at booking and what was delivered, tracks customer reliability through a rolling strike system that can suspend a chronic no-show, and keeps each van's route internally consistent as stops are added, serviced, or freed.

The remainder of this document defines the global API contract (Section 2), the detailed business logic and workflows (Section 3), the endpoint surface (Section 4), and the canonical error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. The `X-User-ID` header conveys the caller's identity, and `X-User-Role` declares the role under which they are acting. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing. If the headers are well-formed but the declared role is not permitted to invoke the requested operation — or an ownership-scoped role attempts to act on a resource it does not own — the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

There are exactly four roles, spelled precisely as follows: `PlatformAdmin`, `Dispatcher`, `Customer`, and `Groomer`.

Two of these roles are tied to a persisted entity. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` (directly, or transitively through a `Pet`) compare the resource's owning customer to `X-User-ID`. A customer may therefore act only on their own pets, their own appointments, their own recurring plans, and their own fee charges. When `X-User-Role` is `Groomer`, `X-User-ID` is the `id` of the acting `Groomer`; ownership checks on a resource that references a `Groomer` compare the resource's `groomer_id` to `X-User-ID`. In particular, a groomer may complete only an appointment whose `groomer_id` equals their own `id`.

The other two roles are operator identities not backed by any persisted entity. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. When `X-User-Role` is `Dispatcher`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity, and the server does not compare it to any entity's `id`.

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

All list endpoints accept two optional query parameters, `limit` and `offset`. The `limit` parameter defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` parameter defaults to 0 and represents the number of leading records to skip. A supplied `limit` outside the 1–100 range, a negative `offset`, or a non-integer value for either is not clamped but is rejected with `ERR_INVALID_REQUEST` (HTTP 422). List results are always sorted by `created_at` in ascending order, so that the oldest record appears first; ties on `created_at` are broken by ascending `id`. Each list response surfaces the effective `limit`, the effective `offset`, the `total_count` of records matching the query before pagination, and a `has_more` boolean indicating whether further records remain beyond the returned page, all carried in the `meta` block described in Section 2.2.

### 2.4. Common Resource Properties and Identifiers

Every persisted resource carries a server-minted `id`, which is a UUID with no type prefix. Every resource also carries a `created_at` timestamp recorded at creation. Timestamps throughout the system — including `created_at`, `updated_at`, and all domain date fields — are ISO 8601 UTC values rendered with three fractional digits.

Most resources additionally carry an `updated_at` timestamp and an integer `version`. The `version` begins at its initial value when the resource is created and increments by one on every mutation; `updated_at` is refreshed to the current clock on each mutation. The following two entities are the exception: a `VaccinationRecord` and an appointment-add-on link carry only an `id` and a `created_at` — they have neither an `updated_at` nor a `version`, because they are immutable once written. Where a calculation or transition below says it "bumps the version" or "refreshes `updated_at`" of a resource, that applies only to versioned resources.

### 2.5. Service Catalog Enumerations

Several configuration entities are defined entirely by enumerated codes that downstream pricing and routing logic keys off of. A `Breed` carries a `coat_type` that is one of `SMOOTH`, `DOUBLE`, `CURLY`, `WIRE`, or `HAIRLESS`, and a `size_class` that is one of `TOY`, `SMALL`, `MEDIUM`, `LARGE`, or `GIANT`. A `ServiceTier` is identified by a `code` that is one of `BATH_ONLY`, `FULL_GROOM`, or `SHOW_CUT`. An `AddOn` is identified by a `code` that is one of `DESHED`, `NAIL_TRIM`, or `TEETH_CLEAN`. A `Groomer` carries a `skill_level` of either `JUNIOR` or `SENIOR` and a `status` of either `AVAILABLE` or `OFF_DUTY`. These enumeration values are stored and compared exactly as written; a request supplying any other value for an enumerated field is malformed and is rejected with `ERR_INVALID_REQUEST` (HTTP 422). `ERR_INVALID_REQUEST` is the general body-well-formedness error: it is raised whenever a required field is missing or null, a field carries the wrong JSON type, a numeric field falls outside its stated bound, a string field that must be an enum holds an unlisted value, a `service_zip`/`coverage_zip` is not exactly five digits, or a uniqueness constraint is violated (see Sections 3.1 and 3.2). The narrower `ERR_VALIDATION` (also HTTP 422) is reserved exclusively for the two date-ordering invariants called out in Sections 3.2 and 3.7.

### 2.6. Derived Field Reconciliation

A handful of fields are never supplied by the client; the server computes and reconciles them, and they reflect the latest inputs at all times. On a `Pet`, the boolean `muzzle_required` is derived: it is true whenever the pet's `behavioral_flag` is `AGGRESSIVE` and false otherwise, and it is recomputed every time `behavioral_flag` changes. Also on a `Pet`, `vaccination_status` is derived to be `VALID` when the pet has at least one `RABIES` vaccination record that has not expired relative to the current clock, and `EXPIRED` otherwise; it is recomputed whenever a vaccination record is uploaded and is evaluated against the current clock at booking time. On a `RouteDay`, the integer `booked_minutes` is a denormalized route-load figure reconciled on every stop addition or cancellation, and the `status` is computed as the route progresses. On a `Customer`, `no_show_strikes`, `account_status`, and `outstanding_fee_cents` are all server-computed aggregates reconciled as fees and strikes are assessed, settled, and waived. The precise computation rules for each of these live in Section 3.

### 2.7. Monetary and Duration Precision

All monetary amounts are integer cents — `base_price_cents`, `price_cents`, `quoted_price_cents`, `final_price_cents`, `amount_cents`, `outstanding_fee_cents`, and the snapshot price are all whole-cent integers. Whenever a pricing rule multiplies by a percentage, the resulting component is rounded half-up to a whole cent at the step the rule specifies, and the order of rounding matters (see Section 3 for which components round individually and which round after summation). Durations are whole integer minutes; the only rounding in the duration calculation is a single ceiling applied to the tier-scaled minutes, after which all additions are integer.

### 2.8. Optimistic Concurrency on Scheduling

Scheduling an appointment onto a route is the one operation that mutates a shared parent resource — the `RouteDay` — and is therefore guarded by optimistic concurrency control. A schedule request must carry `expected_route_day_version`, a non-optional field holding the `version` of the target `RouteDay` that the client last observed. The server compares it to the target route day's current `version`. If they do not match — because a prior schedule legitimately created a stop and recomputed `booked_minutes`, advancing the route day's `version` since the client last read it — the request is rejected with `ERR_STALE_ROUTE_VERSION` (HTTP 412) before any window, overlap, or capacity check runs, since the stale client is reasoning about an out-of-date view of remaining capacity and the route window. No other endpoint takes a version field; only scheduling carries this check.

### 2.9. Left-to-Right Path Validation and Existence

For any request whose URL contains resource identifiers, the server validates the existence of each referenced resource from left to right along the path, and likewise verifies that every foreign-key identifier carried in a request body refers to an existing resource. The first identifier that does not resolve causes the request to be rejected with `ERR_NOT_FOUND` (HTTP 404). For example, when listing the stops of a route day, the route day itself must exist before its stops are considered; when attaching an add-on to an appointment, both the appointment in the path and the `add_on_id` in the body must exist.

### 2.10. The Logical Clock

Several rules — vaccination validity, the late-cancel hour gap, and the rolling strike window — are evaluated against the server's notion of "current clock" rather than wall-clock time. A platform administrator may set this logical clock to a supplied instant, passed as `to_iso8601`, so that time-gated behavior is deterministic; the call returns HTTP 200 with an empty `data` object. Until the clock has been set, the server's notion of "current clock" is the real wall-clock UTC time. All subsequent vaccination-validity and late-cancel-hour computations use the most recently set clock value.

## 3. Business Logic & Workflows

### 3.1. Building the Service Catalog

Before any pet can be groomed, a platform administrator establishes the catalog. A `Breed` is created with a display `name` (unique across all breeds), its `coat_type` and `size_class` enumerations, and a `base_service_minutes` value that seeds the duration calculation; that seed must be at least 15 and at most 240. A `ServiceTier` is created with a `code` (unique across tiers), a `base_price_cents` of at least 0, and a `duration_multiplier` carried to two decimal places that must be at least 1.0 and at most 3.0 — this multiplier scales a breed's baseline minutes for the tier. An `AddOn` is created with a `code` (unique across add-ons), a `price_cents` of at least 0, a `duration_minutes` of at least 0 and at most 60, and a `requires_calm` flag that defaults to false; when `requires_calm` is true the add-on may not be applied to an aggressive pet (see Section 3.6). A `Van` is registered with a unique `label`, a `max_stops` value of at least 1 and at most 20, and a `has_show_equipment` flag defaulting to false that records whether the van can perform show cuts. Groomers are also created by the administrator, each with a unique login `email`, a `full_name`, a `skill_level` of `JUNIOR` or `SENIOR`, a `handles_aggressive` flag defaulting to false, and a `status` defaulting to `AVAILABLE`. Each uniqueness constraint named in this section — breed `name`, service-tier `code`, add-on `code`, van `label`, and groomer `email` — is enforced at creation; an attempt to create a second entity colliding on the unique field is rejected with `ERR_INVALID_REQUEST` (HTTP 422).

### 3.2. Owners, Pets, and Vaccination Proof

A `Customer` is registered with a unique `email`, a `full_name`, and a `service_zip` that must be exactly five digits — the ZIP the van must cover to serve them; a duplicate `email` is rejected with `ERR_INVALID_REQUEST` (HTTP 422). A newly registered owner begins with no strikes recorded, an `account_status` of `ACTIVE`, and no outstanding fees.

An owner registers each animal as a `Pet`, supplying the `customer_id` of the owning customer, the `breed_id` that drives coat-and-size duration, the pet's `name`, and its `weight_lbs` which must be greater than zero. The owner may also supply `coat_condition` (defaulting to `NORMAL`, the alternative being `MATTED`) and `behavioral_flag` (defaulting to `CALM`, the alternatives being `NERVOUS` and `AGGRESSIVE`). At creation the server sets `muzzle_required` to true exactly when the supplied `behavioral_flag` is `AGGRESSIVE` (otherwise false), and sets `vaccination_status` to `EXPIRED` because no records exist yet. An owner may later amend a pet's mutable attributes — `coat_condition`, `behavioral_flag`, and `weight_lbs` — and when `behavioral_flag` is amended the server reconciles `muzzle_required` to match (true if and only if the new flag is `AGGRESSIVE`); each such amendment bumps the pet's `version`.

Rabies compliance is proven by uploading a vaccination record against a pet. Each `VaccinationRecord` carries the `pet_id` it belongs to, a `vaccine_type` (one of `RABIES`, `BORDETELLA`, or `DISTEMPER`, though only `RABIES` gates booking), the `issued_on` date the vaccine was administered, and the `expires_on` date after which it lapses. The `expires_on` value must be strictly later than `issued_on`; a record that violates this ordering is rejected with `ERR_VALIDATION` (HTTP 422). Uploading a record causes the server to recompute the pet's `vaccination_status` against the current clock — it becomes `VALID` if a non-expired `RABIES` record now exists and `EXPIRED` otherwise — and bumps the pet's `version`.

### 3.3. Quoting an Appointment: Duration and Forward-Looking Price

An appointment begins life when a `pet_id` and a `service_tier_id` are submitted to request grooming for a pet at a tier; an optional `recurring_plan_id` marks the appointment as plan-generated. The new appointment enters `REQUESTED` status with a `quote_round` of 0 and all computed pricing and duration fields at their zero defaults. While an appointment is `REQUESTED` (and not yet scheduled), the owner or dispatcher may attach add-ons to it (Section 3.6).

A dispatcher issues a quote, which advances a `REQUESTED` appointment to `QUOTED`. Quoting is permitted only from `REQUESTED` or from an unscheduled `QUOTED` appointment; this state guard is checked before vaccination, so quoting from any other state — or re-quoting an appointment whose `route_stop_id` is already set — is rejected with `ERR_INVALID_STATE` (HTTP 409). The pet's `vaccination_status` must be `VALID` — that is, a non-expired `RABIES` record must exist at the current clock — or the quote is rejected with `ERR_VACCINATION_REQUIRED` (HTTP 422). An already-`QUOTED` appointment that has not yet been scheduled (its `route_stop_id` is still unset) may be re-quoted, which leaves it in `QUOTED`; this cyclic re-quote loop exists so that add-ons or a changed coat condition can be reflected before the appointment is locked onto a route. The vaccination requirement applies to quoting whether the appointment is moving from `REQUESTED` to `QUOTED` or looping `QUOTED` to `QUOTED`. Each quote issuance — first quote or re-quote — recomputes both the duration estimate and the forward-looking price from the pet, tier, and currently attached add-ons, pins them onto the appointment, increments `quote_round` by one, and bumps the appointment's `version`.

**Duration estimate.** The estimate begins from the breed's `base_service_minutes`. That baseline is multiplied by the tier's `duration_multiplier`, and the product is rounded up to the next whole minute; this ceiling is applied exactly once, here. To that tier-scaled figure the server adds a size surcharge of 20 minutes when the pet's `weight_lbs` is greater than 60 pounds (and nothing otherwise), a de-matting allowance of 25 minutes when the pet's `coat_condition` is `MATTED` (and nothing otherwise), and the sum of the `duration_minutes` of every add-on currently attached to the appointment. The resulting whole-minute total is stored as `estimated_minutes`.

**Forward-looking price (the quote).** The quote starts from the tier's `base_price_cents`. A coat loading is added when the pet's `coat_condition` is `MATTED`: it equals 30 percent of the tier base price, rounded half-up to a whole cent at this per-component step (zero when the coat is not matted). A size loading is added when the pet's `weight_lbs` is greater than 60 pounds: it equals 15 percent of the tier base price, rounded half-up to a whole cent at this per-component step (zero otherwise). The add-on total is the sum of the snapshotted `price_cents_snapshot` of every add-on attached at quote time — at quote, this projects the full requested basket. These four parts — tier base, coat loading, size loading, and add-on total — are summed into a gross amount. If the appointment is plan-generated (its `recurring_plan_id` is set), a loyalty discount is computed as the plan's `discount_pct` of that gross, rounded half-up to a whole cent only after the gross has been summed, and subtracted; otherwise the discount is zero. The result is stored as `quoted_price_cents`. This is the projected price at booking, computed before anyone knows which add-ons will actually be delivered.

### 3.4. Scheduling onto a Route: Window, Capacity, Overlap, and Groomer Selection

Scheduling is the most heavily guarded transition in the system. A dispatcher schedules a `QUOTED` appointment onto a route by supplying the target `route_day_id`, the desired `slot_start`, and `expected_route_day_version`; on success the appointment advances to `SCHEDULED`. The checks below are evaluated in the following priority order, and the first failure determines the rejection.

First, the appointment must currently be `QUOTED`; attempting to schedule from any other state yields `ERR_INVALID_STATE` (HTTP 409). Next, the target route day must be accepting stops: scheduling onto a `LOCKED` or `CLOSED` route day is rejected with `ERR_ROUTE_LOCKED` (HTTP 409). Then the pet's `vaccination_status` must again be `VALID` at the current clock, or the request is rejected with `ERR_VACCINATION_REQUIRED` (HTTP 422). Following that, an eligible groomer must exist (the muzzle-and-skill predicate described below); if the candidate pool is empty the request is rejected with `ERR_NO_QUALIFIED_GROOMER` (HTTP 422). The route day's `coverage_zip` must equal the owning customer's `service_zip`, otherwise `ERR_ZIP_NOT_COVERED` (HTTP 422). The requested slot interval — which runs from `slot_start` for a length of `estimated_minutes`, treated as half-open so the end instant is excluded — must fit entirely inside the route day's `[window_start, window_end)` window and must not collide with any other stop, or scheduling fails with `ERR_SLOT_OVERLAP` (HTTP 409); the overlap geometry is detailed below. The number of stops on the route day, counting every `RouteStop` row ever created on the day regardless of status — including `VOIDED` stops, unlike the route-load rule below which excludes them — plus the one being added must not exceed the van's `max_stops`, or `ERR_VAN_STOPS_FULL` (HTTP 409). The owning customer's `account_status` must be `ACTIVE`, not `SUSPENDED`, or `ERR_ACCOUNT_SUSPENDED` (HTTP 422). The route's load plus the new stop's load must fit the window (capacity rule below), or `ERR_ROUTE_CAPACITY_EXCEEDED` (HTTP 409). The supplied `expected_route_day_version` must match the route day's current `version`, or `ERR_STALE_ROUTE_VERSION` (HTTP 412). Finally, when the requested tier's `code` is `SHOW_CUT`, the assigned van must have `has_show_equipment` true and a `SENIOR` groomer must be available in the pool, or the request is rejected with `ERR_SHOW_CUT_UNSUPPORTED` (HTTP 422).

To put the ordering plainly: authentication is checked first, then authorization, then existence of referenced resources, then body well-formedness (`ERR_INVALID_REQUEST`, which here covers a missing or non-integer `expected_route_day_version`, a missing `route_day_id`, or a missing/unparseable `slot_start`), then the appointment's state (`ERR_INVALID_STATE`), then route lock (`ERR_ROUTE_LOCKED`), then vaccination (`ERR_VACCINATION_REQUIRED`), then qualified-groomer existence (`ERR_NO_QUALIFIED_GROOMER`), then ZIP coverage (`ERR_ZIP_NOT_COVERED`), then slot fit and overlap (`ERR_SLOT_OVERLAP`), then van stop count (`ERR_VAN_STOPS_FULL`), then account suspension (`ERR_ACCOUNT_SUSPENDED`), then route capacity (`ERR_ROUTE_CAPACITY_EXCEEDED`), then the stale-version check (`ERR_STALE_ROUTE_VERSION`), and finally show-cut support (`ERR_SHOW_CUT_UNSUPPORTED`).

**Slot fit and overlap geometry.** The requested interval is `[slot_start, slot_start + estimated_minutes)`. For van/route geometry, every other stop on the same route day whose status is `RESERVED`, `SERVICED`, or `NO_SHOW` is expanded by a 15-minute travel buffer on both ends — from 15 minutes before its `slot_start` to 15 minutes after its `slot_end` — and if the requested interval overlaps any such buffered interval, the request is rejected with `ERR_SLOT_OVERLAP`. The requested interval must also lie fully within the route window. Stops in `VOIDED` status are ignored for overlap, since their slot and travel time have been freed.

**Route load capacity.** A route day's window length is the whole number of minutes from `window_start` to `window_end`. Each non-voided stop consumes its service minutes plus one 15-minute travel buffer, so the route's existing load is the sum over every stop with status `RESERVED`, `SERVICED`, or `NO_SHOW` of that stop's `scheduled_minutes` plus 15. The new stop's load is the appointment's `estimated_minutes` plus 15. Scheduling is permitted only when the existing load plus the new load is at most the window length in minutes; the boundary is inclusive, so exactly filling the window is allowed and one minute beyond is rejected with `ERR_ROUTE_CAPACITY_EXCEEDED`. The persisted `booked_minutes` on the route day denormalizes that existing load (service minutes plus a 15-minute buffer for each non-voided stop) and is reconciled on every stop addition or cancellation.

**Groomer selection.** The server, not the client, picks the groomer. The candidate pool consists of groomers whose `status` is `AVAILABLE`, who can handle the pet (either the pet's `muzzle_required` is false, or the groomer's `handles_aggressive` is true), who can deliver the tier (either the tier's `code` is not `SHOW_CUT`, or the groomer's `skill_level` is `SENIOR`), and who are free at the requested time. For the free-at-time test, a candidate groomer's own non-voided stops are compared using their raw `[slot_start, slot_end)` intervals with no travel buffer, so two appointments that are exactly back-to-back (one stop's `slot_end` equal to the next stop's `slot_start`) are allowed and only a true overlap excludes the groomer. Among the candidates, the server prefers a `SENIOR` over a `JUNIOR` groomer; ties are broken by preferring the groomer with the fewest `RESERVED` stops already assigned to them on this route day (ascending); any remaining tie is broken by earliest `created_at`. The first candidate by this ranking is selected; if the pool is empty, `ERR_NO_QUALIFIED_GROOMER` is raised.

**On successful scheduling**, the server creates a new `RouteStop` in `RESERVED` status with its `scheduled_minutes` copied from the appointment's `estimated_minutes` and its `slot_end` set to `slot_start` plus those minutes; it sets the appointment's `route_stop_id` to the new stop and its `groomer_id` to the selected groomer; it recomputes the route day's `booked_minutes`; it bumps the route day's `version` and the appointment's `version`. The route stop belongs to its route day as a child and carries that day's identifier in `route_day_id`.

### 3.5. Completing, No-Showing, and Cancelling

When the van arrives and the work is done, the assigned groomer completes the appointment, advancing it from `SCHEDULED` to `COMPLETED`; completing (or recording a no-show on) an appointment that is not currently `SCHEDULED` is rejected with `ERR_INVALID_STATE` (HTTP 409). Only the groomer whose `id` equals the appointment's `groomer_id` may complete it. The `skipped_add_on_ids` field is optional; when omitted or null it defaults to an empty list (nothing skipped), and a non-list value is rejected with `ERR_INVALID_REQUEST` (HTTP 422). At completion the groomer may pass `skipped_add_on_ids`, the list of add-on identifiers that could not be delivered. The server computes the **final price** chronologically from what was actually delivered: it starts from the tier `base_price_cents`, adds the same coat loading (30 percent of tier base, rounded half-up, when the pet is `MATTED`) and size loading (15 percent of tier base, rounded half-up, when `weight_lbs` exceeds 60 pounds) as the quote, then adds the add-on total counting only the snapshotted prices of attached add-ons whose `add_on_id` is not in `skipped_add_on_ids`. Those four parts are summed into a delivered gross; if the appointment is plan-generated, the same loyalty discount (the plan's `discount_pct` of the delivered gross, rounded half-up after summation) is subtracted; the result is stored as `final_price_cents`. Whenever a requested add-on is skipped, the final price is strictly less than the quote, so `quoted_price_cents` and `final_price_cents` legitimately differ. On completion the linked route stop transitions to `SERVICED`; if that makes every stop on the route day terminal, the route day bubbles up to `CLOSED` (see Section 3.7); and the appointment's `version` is bumped.

A dispatcher records a no-show when a scheduled pet fails to appear, advancing the appointment from `SCHEDULED` to `NO_SHOW`. The no-show may only be recorded once the current clock has reached the reserved stop's `slot_start` (the clock is at or after `slot_start`); an attempt before `slot_start` is rejected with `ERR_INVALID_STATE` (HTTP 409). Recording it sets the linked route stop's status to `NO_SHOW` — note that a no-show stop still consumed its slot and remains counted in route load. The server then assesses a no-show fee and, in a depth-three cascade (appointment to fee to customer), debits the customer's `outstanding_fee_cents` by the assessed amount and registers a strike that recomputes the customer's `no_show_strikes`, suspending the account if the threshold is reached. The route day's `booked_minutes` is recomputed (a `NO_SHOW` stop remains counted), and the appointment's `version` is bumped.

**No-show fee.** The fee starts at 50 percent of the appointment's pinned `quoted_price_cents`, rounded half-up to a whole cent. The customer's strike count is read immediately before this no-show is registered: if that prior count is at least 2, a flat repeat penalty of 1500 cents is added to the percent-of-quote base; otherwise no penalty is added. The resulting amount is then capped at 8000 cents — the final fee is the smaller of the computed amount and 8000 cents. Because the repeat penalty depends on the customer's strike posture before the event, the same appointment and the same quote can produce a strictly larger fee for a repeat offender than for a first-time no-show; the escalation lives on the customer, not on the appointment.

An owner may cancel their own appointment. Cancelling a `REQUESTED` appointment moves it to `CANCELLED` with no fee, because it was never scheduled. Cancelling a `QUOTED` appointment likewise moves it to `CANCELLED` with no fee. Cancelling a `SCHEDULED` appointment moves it to `CANCELLED`, sets the linked route stop to `VOIDED` (which frees the slot and its travel buffer), and recomputes the route day's `booked_minutes`. A scheduled cancellation may additionally be a **late cancel**: the server measures the whole-hour gap from the current clock to the reserved `slot_start`, taking the floor to whole hours. If that gap is at least 24 hours the cancellation is not late and there is no fee and no strike; if it is fewer than 24 hours the customer is charged a flat 2500-cent late-cancel fee, the same depth-three cascade debits `outstanding_fee_cents`, and a strike is registered with `no_show_strikes` and `account_status` recomputed. In every cancellation case the appointment's `version` is bumped. Cancellation is permitted only from `REQUESTED`, `QUOTED`, or `SCHEDULED`; attempting to cancel an appointment already in a terminal state (`COMPLETED`, `NO_SHOW`, or `CANCELLED`) is rejected with `ERR_INVALID_STATE` (HTTP 409). Only the owning customer may cancel; an attempt by another customer is forbidden.

### 3.6. Attaching Add-Ons and the Calm Requirement

An add-on is attached to a not-yet-scheduled appointment by supplying the `add_on_id` of the catalog add-on; the appointment is identified by the path. An appointment counts as not-yet-scheduled while its `route_stop_id` is unset and its status is `REQUESTED` or `QUOTED`; attaching to an appointment that has been scheduled or has reached a terminal state (`SCHEDULED`, `COMPLETED`, `NO_SHOW`, or `CANCELLED`) is rejected with `ERR_INVALID_STATE` (HTTP 409). Attaching creates an appointment-add-on link recording the `appointment_id` and `add_on_id`, snapshots the catalog add-on's current `price_cents` into the link's `price_cents_snapshot` so that later catalog edits never alter this appointment's quote, and bumps the appointment's `version`. The snapshot is the price that flows into both the quote and the final-price add-on totals. If the add-on's `requires_calm` flag is true and the appointment's pet has a `behavioral_flag` of `AGGRESSIVE`, the attachment is rejected with `ERR_ADDON_NOT_ALLOWED` (HTTP 422), because a calm-requiring service cannot be performed on an aggressive animal.

### 3.7. Route Days and Their Lifecycle

A route day is created for a particular van by supplying the `van_id`, the `service_date` (the calendar date at midnight UTC), the `window_start` and `window_end` clock times that bound the service window, and the `coverage_zip` (exactly five digits) naming the neighborhood the van serves that day. The `window_end` must be strictly after `window_start`, or the creation is rejected with `ERR_VALIDATION` (HTTP 422). A new route day opens in `OPEN` status with `booked_minutes` at zero. While `OPEN` the route day accepts stops, which are created implicitly by scheduling appointments (Section 3.4); each route stop carries its `route_day_id`, `slot_start`, computed `scheduled_minutes`, computed `slot_end`, and a `status` that starts at `RESERVED`.

A dispatcher dispatches a route day to lock it, advancing it from `OPEN` to `LOCKED`; this requires that the route day is currently `OPEN` and that at least one stop on the day is in `RESERVED` status. Dispatching a route day that is not `OPEN`, or one that has no `RESERVED` stop, is rejected with `ERR_INVALID_STATE` (HTTP 409). Once `LOCKED`, no new stops may be added — any attempt to schedule onto it is rejected with `ERR_ROUTE_LOCKED` — and the route day's `version` is bumped. A route day transitions automatically from `LOCKED` to `CLOSED` as a bubble-up side effect the moment every stop on the day has reached a terminal status (`SERVICED`, `NO_SHOW`, or `VOIDED`); this auto-transition fires when the last stop becomes terminal (typically on completion) and bumps the route day's `version`. The route day's `status` therefore reads `OPEN` while accepting stops, `LOCKED` once dispatched, and `CLOSED` once fully resolved.

### 3.8. Recurring Grooming Plans

A recurring plan automates repeat bookings for a pet. It is created with the `pet_id`, the `service_tier_id` to auto-apply to generated appointments, a `cadence_days` value that must be one of 28, 42, or 56, and a `discount_pct` loyalty discount carried to two decimal places that must be at least 0 and at most 0.20. A new plan starts in `ACTIVE` status. An active plan generates appointments; a paused plan suspends generation; a cancelled plan is terminal.

The owning customer — the customer who owns the plan's pet — may pause an `ACTIVE` plan, moving it to `PAUSED` and suspending generation, and may resume a `PAUSED` plan back to `ACTIVE` to resume generation. The owner may also cancel a plan from either `ACTIVE` or `PAUSED`, moving it to the terminal `CANCELLED` state. Each of these transitions bumps the plan's `version`, and each requires that the acting customer owns the plan's pet. A transition attempted from a disallowed source state — pausing a plan that is not `ACTIVE`, resuming one that is not `PAUSED`, or cancelling one that is already `CANCELLED` — is rejected with `ERR_INVALID_STATE` (HTTP 409).

A dispatcher drives generation of the next appointment from an `ACTIVE` plan; this is a cyclic self-loop that leaves the plan `ACTIVE`. Generation requires that the plan is `ACTIVE` and that the owning customer's `account_status` is `ACTIVE` (a `SUSPENDED` customer cannot have new appointments generated, rejected with `ERR_ACCOUNT_SUSPENDED`). The plan-state check runs first: generating from a plan that is not `ACTIVE` (it is `PAUSED` or `CANCELLED`) is rejected with `ERR_INVALID_STATE` (HTTP 409) before the customer's account standing is examined. Generation creates a new `REQUESTED` appointment with its `recurring_plan_id` set to this plan and its `service_tier_id` copied from the plan, and bumps the plan's `version`. The cadence value `cadence_days` governs the spacing the operator intends between generated appointments.

### 3.9. Fees, Strikes, and Account Standing

Every assessed fee is recorded as a `FeeCharge` carrying the owning `customer_id`, the triggering `appointment_id`, a `fee_type` of either `NO_SHOW` or `LATE_CANCEL`, the computed `amount_cents`, and a `settlement_status`. A fee begins `PENDING` when assessed; the owning customer may settle it, moving it to `SETTLED`; a platform administrator may waive it, moving it to `WAIVED`. Both settle and waive require the fee to currently be `PENDING`; attempting either on a fee already `SETTLED` or `WAIVED` is rejected with `ERR_INVALID_STATE` (HTTP 409). Only the customer named on the fee may settle it.

The customer's `outstanding_fee_cents` is maintained as the sum of `amount_cents` over that customer's `PENDING` fee charges — it is debited when a fee is assessed and credited back when a fee is settled or waived, preserving the invariant that it always equals the total of the customer's pending fees. Settling a `PENDING` fee credits the customer's `outstanding_fee_cents` by the fee's `amount_cents` and bumps the fee's `version`. Waiving a `PENDING` fee likewise credits `outstanding_fee_cents` by `amount_cents`, and additionally reverses the strike the fee represented: it decrements the customer's `no_show_strikes` by one and recomputes `account_status` accordingly, then bumps the fee's `version`. Settling does not remove a strike; only waiving does.

**Strike accounting.** A strike is recorded for each `NO_SHOW` fee charge and each late `LATE_CANCEL` fee charge whose `settlement_status` is not `WAIVED`. The customer's `no_show_strikes` is the count of such non-waived strike events whose triggering appointment's reserved `slot_start` falls within the trailing 90 days of the current clock — that is, at or after the instant 90 days before the current clock; the 90-day boundary is inclusive. The customer's `account_status` is `SUSPENDED` when `no_show_strikes` is at least 3 and `ACTIVE` otherwise; the suspension boundary is inclusive at exactly 3. This rolling count is recomputed on each strike event and read at booking time, which is how a chronic no-show becomes blocked from scheduling and from plan generation until enough strikes age out of the window or are waived.

## 4. Endpoint Definitions

All endpoints share the response envelope of Section 2.2. Endpoints that create a brand-new resource return HTTP 201; endpoints that fetch, list, or modify an existing resource (including state transitions) return HTTP 200. Request bodies, side effects, and computed outputs are described in Section 3; the table below lists only the method, path, purpose, and authorized roles.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /breeds | Create a breed configuration | PlatformAdmin |
| GET | /breeds/{id} | Fetch a breed | PlatformAdmin, Dispatcher, Customer, Groomer |
| POST | /service-tiers | Create a service tier | PlatformAdmin |
| POST | /add-ons | Create an add-on catalog entry | PlatformAdmin |
| POST | /vans | Register a van | PlatformAdmin, Dispatcher |
| POST | /customers | Register an owner | PlatformAdmin, Customer |
| GET | /customers/{id} | Fetch an owner with computed strike/fee fields | PlatformAdmin, Dispatcher, Customer |
| GET | /customers/{id}/pets | List a customer's pets | PlatformAdmin, Dispatcher, Customer |
| GET | /customers/{id}/fee-charges | List a customer's fee charges | PlatformAdmin, Dispatcher, Customer |
| POST | /pets | Create a pet under an owner | PlatformAdmin, Customer |
| GET | /pets/{id} | Fetch a pet with computed muzzle/vaccination fields | PlatformAdmin, Dispatcher, Customer, Groomer |
| GET | /pets | List pets, filterable by owner or breed | PlatformAdmin, Dispatcher, Customer |
| PATCH | /pets/{id} | Update mutable pet fields; reconciles derived fields | PlatformAdmin, Customer |
| GET | /pets/{id}/vaccinations | List a pet's vaccination records | PlatformAdmin, Dispatcher, Customer |
| POST | /pets/{id}/vaccinations | Upload a vaccination proof record for a pet | PlatformAdmin, Customer |
| POST | /groomers | Create a groomer | PlatformAdmin |
| GET | /groomers/{id} | Fetch a groomer | PlatformAdmin, Dispatcher, Groomer |
| POST | /route-days | Create a route day for a van | PlatformAdmin, Dispatcher |
| GET | /route-days/{id} | Fetch a route day with computed status and booked_minutes | PlatformAdmin, Dispatcher, Groomer |
| GET | /route-days/{id}/stops | List stops on a route day | PlatformAdmin, Dispatcher, Groomer |
| POST | /route-days/{id}/dispatch | Lock a route day so no new stops may be added | PlatformAdmin, Dispatcher |
| GET | /route-days | List route days, filterable by van | PlatformAdmin, Dispatcher |
| GET | /route-stops/{id} | Fetch a route stop | PlatformAdmin, Dispatcher, Groomer |
| GET | /route-stops | List route stops, filterable by route day | PlatformAdmin, Dispatcher, Groomer |
| POST | /appointments | Create an appointment request for a pet at a tier | PlatformAdmin, Dispatcher, Customer |
| GET | /appointments/{id} | Fetch an appointment with computed pricing/duration/assignment fields | PlatformAdmin, Dispatcher, Customer, Groomer |
| GET | /appointments | List appointments, filterable by pet, tier, route stop, groomer, or plan | PlatformAdmin, Dispatcher, Customer, Groomer |
| POST | /appointments/{id}/add-ons | Attach an add-on to a not-yet-scheduled appointment | PlatformAdmin, Dispatcher, Customer |
| GET | /appointments/{id}/add-ons | List add-ons attached to an appointment | PlatformAdmin, Dispatcher, Customer, Groomer |
| GET | /add-on-links/{id} | Fetch a single appointment-addon link | PlatformAdmin, Dispatcher, Customer, Groomer |
| GET | /add-on-links | List appointment-addon links, filterable by add-on or appointment | PlatformAdmin, Dispatcher |
| POST | /appointments/{id}/quote | Issue or re-issue a quote (duration + price) | Dispatcher |
| POST | /appointments/{id}/schedule | Schedule a quoted appointment onto a route day slot | Dispatcher |
| POST | /appointments/{id}/complete | Groomer marks the appointment completed; final price computed | Groomer |
| POST | /appointments/{id}/no-show | Dispatcher records a no-show; assesses fee and strike | Dispatcher |
| POST | /appointments/{id}/cancel | Owner cancels; late cancels of scheduled appointments assess a flat fee + strike | Customer |
| POST | /recurring-plans | Create a recurring grooming plan for a pet | PlatformAdmin, Dispatcher, Customer |
| GET | /recurring-plans/{id} | Fetch a recurring plan | PlatformAdmin, Dispatcher, Customer |
| GET | /recurring-plans | List recurring plans, filterable by pet or service tier | PlatformAdmin, Dispatcher, Customer |
| POST | /recurring-plans/{id}/pause | Pause generation | Customer |
| POST | /recurring-plans/{id}/resume | Resume generation | Customer |
| POST | /recurring-plans/{id}/cancel | Cancel a plan (terminal) | Customer |
| POST | /recurring-plans/{id}/generate-appointment | Generate the next appointment from an active plan | Dispatcher |
| GET | /fee-charges/{id} | Fetch a fee charge | PlatformAdmin, Dispatcher, Customer |
| GET | /fee-charges | List fee charges, filterable by customer or appointment | PlatformAdmin, Dispatcher, Customer |
| POST | /fee-charges/{id}/settle | Owner settles a pending fee | Customer |
| POST | /fee-charges/{id}/waive | Admin waives a pending fee and reverses its strike | PlatformAdmin |
| POST | /_clock/set_current_utc | Set the server's current UTC clock for deterministic time-gated tests | PlatformAdmin |

## 5. Error Code Catalogue

The trigger conditions for each error are described in the narrative of Sections 2 and 3; this catalogue lists only the canonical identifiers and their HTTP status codes.

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 422 |
| ERR_INVALID_STATE | 409 |
| ERR_ROUTE_LOCKED | 409 |
| ERR_VACCINATION_REQUIRED | 422 |
| ERR_NO_QUALIFIED_GROOMER | 422 |
| ERR_ZIP_NOT_COVERED | 422 |
| ERR_SLOT_OVERLAP | 409 |
| ERR_VAN_STOPS_FULL | 409 |
| ERR_ACCOUNT_SUSPENDED | 422 |
| ERR_ROUTE_CAPACITY_EXCEEDED | 409 |
| ERR_ADDON_NOT_ALLOWED | 422 |
| ERR_STALE_ROUTE_VERSION | 412 |
| ERR_SHOW_CUT_UNSUPPORTED | 422 |
| ERR_VALIDATION | 422 |

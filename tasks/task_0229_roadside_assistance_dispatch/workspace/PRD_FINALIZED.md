# Roadside Assistance Dispatch API — Product Requirements Document

## 1. Introduction

Stranded motorists need help fast, and the value a roadside-assistance program delivers is measured in minutes: how quickly a qualified tow truck or service technician reaches a breakdown, and how predictably the member is charged for it. This document specifies the Roadside Assistance Dispatch API, a platform that connects members enrolled on tiered coverage plans with a network of vetted service providers, coordinates GPS-based dispatch and arrival-time estimation, and reconciles the costs of each incident against the member's plan benefits.

The platform balances two scarce resources at once. On one side, every member draws against a finite annual quota of covered service calls and a finite per-incident towing allowance, with overage charges accruing beyond that allowance. On the other side, the provider network — trucks with specific capabilities, on-call shift windows, and limited repair-bay capacity at depots — is a competed-for pool that the dispatch engine must allocate fairly and by priority. The API governs the full lifecycle of a service call from the moment a member reports a breakdown, through the offer-and-accept dispatch loop, the technician's travel and on-scene work, final cost reconciliation, and any subsequent out-of-pocket reimbursement claim.

This specification is written for the engineering team implementing the service. It describes the entities, their state machines, the pricing and ranking calculations, the validation rules and their precedence, and the access-control model, with enough precision that an implementation built solely from this document will behave identically to the intended design.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the capacity in which they are acting. The platform recognizes exactly three roles: `DispatchOperator`, `Member`, and `ServiceProvider`. If either header is missing, or if `X-User-Role` does not name one of these three known roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the acting role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The three roles relate to persisted identity differently. When `X-User-Role` is `DispatchOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server treats the operator as the platform's back-office actor and does not compare `X-User-ID` to any entity's `id`. A `DispatchOperator` provisions plans, members, providers, and depots, schedules dispatch and bay reservations, abandons calls, and adjudicates claims. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a member compare that resource's member reference to `X-User-ID` — a member may act only on its own service calls and its own reimbursement claims. When `X-User-Role` is `ServiceProvider`, `X-User-ID` is the `id` of the acting `ServiceProvider`; ownership checks compare the relevant provider reference (the offer's provider, the call's assigned provider, or the shift's provider) to `X-User-ID`. When an operation requires resource ownership and the acting member or provider does not own the targeted resource, the request is rejected with `ERR_NOT_RESOURCE_OWNER`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the number of items to skip from the front of the result set; it defaults to 0 and may not be negative. A `limit` outside the inclusive range of 1 through 100, or a negative `offset`, is rejected with `ERR_INVALID_PAGINATION`.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by their creation timestamp in ascending order. The `meta` object of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` reflects the total number of matching resources before the limit/offset window is applied and `has_more` indicates whether further pages remain.

### 2.4. Common Resource Properties and Versioning

Every primary resource — `MembershipPlan`, `Member`, `ServiceProvider`, `ProviderShift`, `Depot`, `BayReservation`, `ServiceCall`, `DispatchOffer`, and `ReimbursementClaim` — carries a server-managed `id` formatted as a UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC value with three fractional digits at the moment of creation. All of these resources are mutable over their lifetime, so each additionally carries an `updated_at` timestamp (ISO 8601 UTC, three fractional digits) refreshed on every modification and a `version` integer that begins at the resource's creation and increments by one on every mutation. Clients must never supply `id`, `created_at`, `updated_at`, or `version`; the server owns them entirely.

The `version` integer doubles as the optimistic-concurrency token described in §2.7. Whenever a state transition or a recomputation of a derived field mutates a resource, that resource's `updated_at` is refreshed and its `version` advances. This holds for cascaded mutations as well: when an action on one resource propagates a change into a second resource, the second resource's own `updated_at` and `version` move independently of the first.

### 2.5. Geographic Distance and Arrival-Time Estimation

Distances throughout the platform are great-circle distances computed with the haversine formula over latitude/longitude coordinates expressed in decimal degrees, using an Earth radius of 3958.7613 miles. Latitudes are constrained to the range −90 through 90 and longitudes to the range −180 through 180; coordinates outside these bounds are rejected as invalid requests. For distance comparisons and stored distance fields, distances are taken to three decimal places.

Two distances are computed by the system. At the moment a service call is created, if it is a tow the system computes `tow_distance_miles` as the haversine distance from the breakdown location to the drop-off location; for non-tow service this distance is 0. At the moment an offer is dispatched, the system computes `offer_distance_miles` as the haversine distance from the provider's current location to the breakdown location. From that offer distance the system derives an estimated time of arrival: `eta_minutes` is the offer distance in miles divided by an assumed average travel speed of 40 miles per hour, multiplied by 60 to convert hours to minutes, and then rounded up to the next whole minute. The arrival estimate is therefore always a whole number of minutes.

### 2.6. Monetary Precision and the Pinned Rounding Order

All money in the system is expressed in integer cents; there are no fractional cents and no rounding is needed once a value is in cents. Mileage allowances and reported distances, however, carry fractional precision, and the order in which the system rounds matters. For any tow overage charge, the system follows a pinned three-step regime: first it determines the overage mileage (the towed distance beyond the plan's free allowance, never less than zero) and rounds that mileage to three decimal places using round-half-up; second it multiplies the rounded overage mileage by the plan's per-mile overage rate in cents; third it rounds that product to whole cents using round-half-up. This is a round-then-multiply-then-round sequence, and it must be applied in exactly this order — rounding the mileage before multiplying, never after — so that the estimated and final charges are reproducible to the cent.

### 2.7. Optimistic Concurrency on Service-Call Dispatch

Dispatching a new offer against a service call is guarded by optimistic concurrency control, because the same call may legitimately be re-offered several times and an operator can be working from a stale view. The dispatch request must carry `expected_service_call_version`, which is the `version` of the target `ServiceCall` that the operator last observed. The server compares it against the call's current `version`. If they match, the dispatch proceeds; if they differ — for example because another operator already dispatched an offer and thereby advanced the call's version — the dispatch is rejected with `ERR_STALE_CALL_VERSION` and an HTTP 412 status, preventing the operator from over-issuing a second live offer on top of one it never saw. This concurrency token is required on offer dispatch and is not used by any other endpoint; no other write accepts a version field.

### 2.8. Nested Resource Retrieval and Existence Ordering

Many resources are addressed beneath a parent in the URL — offers beneath a service call, shifts beneath a provider, bay reservations beneath a depot. For any request whose path or body references one or more resource identifiers, the system validates their existence left to right, in the order they appear in the path and then the body's foreign-key fields. The first identifier that does not resolve to an existing resource causes the request to be rejected immediately with `ERR_NOT_FOUND`, before any deeper validation runs. A request for an offer beneath a non-existent call, for instance, fails on the call before the offer is ever consulted.

### 2.9. Validation Precedence

When several checks could reject a single request, they are evaluated in a fixed precedence so that the returned error is deterministic. Authentication comes first: a missing or unknown user context yields `ERR_UNAUTHENTICATED`. Role authorization comes next: a recognized user acting outside its permitted operations yields `ERR_FORBIDDEN_ROLE`. Existence comes third: any referenced path or foreign-key resource that does not exist yields `ERR_NOT_FOUND`, evaluated left to right per §2.8. Resource ownership comes fourth: a member or provider acting on a resource it does not own yields `ERR_NOT_RESOURCE_OWNER`. State legality comes fifth: an operation attempted from a state in which the transition is not defined yields `ERR_INVALID_STATE`. Only after these five gates do the domain-specific business rules described throughout §3 run, followed last by structural request-body validation (`ERR_INVALID_REQUEST`) and pagination validation (`ERR_INVALID_PAGINATION`) where applicable. Where a workflow narrative below introduces a business rule, the order in which that rule fires relative to its siblings is stated alongside it.

### 2.10. The Clock and Test-Driving

Time-sensitive behavior — shift-window containment, the annual usage period, and completion timestamps — is evaluated against the server's notion of the current UTC instant, which is also the value stamped into `created_at`. For deterministic testing, an operator-only capability pins this clock to a supplied instant via a `to_iso8601` value; once set, that instant governs `created_at`, shift-window containment, annual-period advancement, and completion timestamps until changed.

## 3. Business Logic & Workflows

### 3.1. Coverage Plans and the Benefits They Encode

A `DispatchOperator` defines the catalog of coverage by creating membership plans. Each plan is created with a `tier` — one of `BASIC`, `PLUS`, or `PREMIER`, and no two plans may share the same tier — together with the benefit parameters that the rest of the system reads. The `annual_service_limit` is the maximum number of dispatched-and-completed service calls a member on the plan may consume within an annual period, and must be at least 1. The `per_incident_mileage_cap_miles` is the free towing distance, in miles, covered on a single tow incident before overage applies; it may not be negative and is carried to as many as three decimal places. The `overage_rate_cents_per_mile` is the member-paid charge, in whole cents, for each mile towed beyond that free allowance, and may not be negative. The `priority_weight` is a positive integer (at least 1) used to order members when providers are scarce; by convention `PREMIER` outranks `PLUS` outranks `BASIC`, but the server reads only the numeric field. The `covered_service_types` is a non-empty list drawn from `TOW`, `JUMP`, `LOCKOUT`, `FUEL`, and `TIRE`, naming the service types for which no out-of-pocket base fee applies. The `base_service_fee_cents` is the out-of-pocket base fee, in cents (at least 0), charged when a member requests a service type that is not in the plan's covered list.

Plans are readable by any authenticated role and listable with an optional `tier` filter; creation is reserved to the operator.

### 3.2. Members, Their Standing, and the Annual Period

Operators register members onto a plan. A new member is created with `plan_id` naming the plan they enroll on, a `full_name`, and a home location given as `home_lat` and `home_lng` in decimal degrees. At registration the server sets the member's `status` to `ACTIVE`, sets `services_used_this_year` to 0, sets `outstanding_balance_cents` to 0, and sets `annual_period_start` to the member's `created_at`. The member `status` is one of `ACTIVE` or `SUSPENDED`. An operator may move a member to `SUSPENDED`, and may later return a suspended member to `ACTIVE`; these are the only two states.

The annual period is a rolling 365-day window that begins at `annual_period_start`. The field `services_used_this_year` counts the member's service calls that reached `COMPLETED` within the current period — the half-open window running from `annual_period_start` up to but not including `annual_period_start` plus 365 days. The field `outstanding_balance_cents` is a conserved quantity: it equals the sum of `member_out_of_pocket_cents` across the member's `COMPLETED` service calls minus the sum of `approved_amount_cents` across the member's `APPROVED` reimbursement claims. Members are fetchable by their owner or an operator and the fetch includes the computed `services_used_this_year` and `outstanding_balance_cents`; operators may list members filtered by `plan_id` or `status`.

A member's standing gates new work. Before a service call may be created, the requesting member's `status` must be `ACTIVE`; a call requested for a member whose status is not `ACTIVE` is rejected with `ERR_MEMBERSHIP_NOT_ACTIVE`. This business check runs after authentication, authorization, existence, ownership, and state checks have passed.

### 3.3. The Provider Network and On-Call Shifts

Operators register service providers into the network. A provider is created with a `company_name`, a current location given as `current_lat` and `current_lng`, a `capabilities` list (a non-empty subset of `TOW`, `JUMP`, `LOCKOUT`, `FUEL`, and `TIRE`) naming the service types it can perform, and a `rating` between 0.0 and 5.0 carried to two decimal places, which serves as the primary ranking key in dispatch. At creation the provider's `status` is `AVAILABLE` and its `active_call_id` is null. The `status` is one of `AVAILABLE`, `ON_JOB`, or `OFFLINE`. The `active_call_id` is a denormalized back-pointer to the service call a provider is currently working — it is set when the provider accepts an offer and cleared when the call completes or is cancelled, and it is null whenever the provider is `AVAILABLE` or `OFFLINE`; it is not an ownership foreign key.

A provider may take itself out of rotation, moving from `AVAILABLE` to `OFFLINE`, and may return, moving from `OFFLINE` back to `AVAILABLE`; each of these is permitted only from the stated source state and is otherwise rejected as an illegal state change. Providers are fetchable by their owner or an operator, and listable with an optional `status` filter.

On-call availability is expressed through shifts. A shift is scheduled with `provider_id`, a `shift_start`, and a `shift_end`, and represents a half-open on-call window inclusive of `shift_start` and exclusive of `shift_end`; `shift_end` must be strictly after `shift_start`, and a violation is an invalid request. A new shift is created in `SCHEDULED` status, the only non-terminal value; the other value is `CANCELLED`. A shift may not be admitted if its half-open window overlaps, with positive measure, an existing `SCHEDULED` shift for the same provider; pure adjacency, where one shift's `shift_end` exactly equals another's `shift_start`, is allowed, but any genuine overlap is rejected with `ERR_SHIFT_OVERLAP`. Both an operator and the provider itself may schedule a shift and may cancel a scheduled shift, which moves it to `CANCELLED`. A provider's shifts are listable (reverse lookup by `provider_id`) with an optional `status` filter.

### 3.4. Depots, Repair Bays, and Their Finite Capacity

Operators run depots where towed vehicles are dropped and stored. A depot is created with a `name`, a location given as `lat` and `lng`, a `bay_count` of at least 1 giving the total number of repair bays, and a `cleanup_buffer_minutes` of at least 0. The buffer is the number of minutes a bay stays blocked after a reservation's nominal end before it can be reused, effectively extending each reservation's occupancy window. A depot also exposes `occupied_bays`, a conserved quantity equal to the count of the depot's bay reservations currently in `ACTIVE` status, which must never exceed `bay_count`. The fetch of a depot includes the computed `occupied_bays`. Depots are readable and listable by any authenticated role.

A bay reservation holds a bay at a depot for a towed vehicle's drop-off window. An operator creates one with `depot_id`, `service_call_id` naming the tow call whose vehicle occupies the bay, a `reserved_from`, and a `reserved_until`; these define a closed occupancy window inclusive of both ends, where `reserved_until` may not be earlier than `reserved_from` (a violation is an invalid request). A reservation begins in `ACTIVE` status, the only other value being `RELEASED`. The effective block on a bay runs from `reserved_from` through `reserved_until` plus the depot's `cleanup_buffer_minutes`. A new reservation is rejected when, across its own buffered closed window, the depot already has a number of `ACTIVE` reservations equal to `bay_count` whose buffered windows overlap it — that is, when admitting it would mean more concurrently occupied bays than the depot has; this aggregate-capacity conflict is rejected with `ERR_NO_BAY_AVAILABLE`. Admitting a reservation increments the depot's `occupied_bays` by one. Releasing a reservation moves it from `ACTIVE` to `RELEASED` and decrements the depot's `occupied_bays` by one, freeing the bay; the release advances the reservation's `version`. Reservations are listable under a depot, filterable by `status` and by `service_call_id`, and the same reservations are reachable beneath their tow call by `service_call_id`.

### 3.5. Opening a Service Call and the Provisional Estimate

A member — or an operator filing on the member's behalf — opens a service call to report a breakdown. The request carries `member_id`, the requested `service_type` (one of `TOW`, `JUMP`, `LOCKOUT`, `FUEL`, `TIRE`), and the breakdown location as `breakdown_lat` and `breakdown_lng`. When `service_type` is `TOW`, the drop-off location given as `dropoff_lat` and `dropoff_lng` is required; for any other service type the drop-off coordinates are ignored. A tow request that omits drop-off coordinates is an invalid request. Subject to the member being `ACTIVE` (§3.2), the call is created in `DISPATCHING` status — the initial state of every call — with `dispatch_attempts` set to 0 and `assigned_provider_id` null. The full lifecycle states are `DISPATCHING`, `ASSIGNED`, `EN_ROUTE`, `COMPLETED`, `CANCELLED`, and `UNFULFILLED`, of which the last three are terminal.

At creation the system fixes the tow geometry and the provisional cost. For a tow it computes `tow_distance_miles` as the haversine distance from breakdown to drop-off; for non-tow service `tow_distance_miles` is 0. It then computes `estimated_cost_cents`, the provisional out-of-pocket estimate, as the sum of a base component and a tow-overage component. The base component is the plan's `base_service_fee_cents` when the requested `service_type` is not among the plan's `covered_service_types`, and 0 when it is covered. The overage component is 0 for any non-tow call; for a tow it is computed from `tow_distance_miles` using the pinned rounding regime of §2.6 — the towed distance beyond the plan's `per_incident_mileage_cap_miles` (never below zero) is rounded to three decimals, then multiplied by `overage_rate_cents_per_mile`, then rounded to whole cents. Thus a covered tow contributes only overage, while an uncovered tow adds the base fee on top of the overage, and an uncovered non-tow contributes only the base fee. The fields `final_cost_cents`, `member_out_of_pocket_cents`, and `final_towed_miles` remain at their defaults of 0 until completion.

Calls are fetchable by an operator, the owning member, or a provider; they are listable filtered by `member_id` or `status`.

### 3.6. Dispatch Candidate Ranking

Before committing an offer, an operator can ask the system for the ranked pool of providers eligible to serve a call — a computed read that drives priority dispatch. A provider is eligible only when all of the following hold: its `status` is `AVAILABLE`; its `capabilities` include the call's `service_type`; the haversine distance from the provider's current location to the call's breakdown location is no greater than the maximum dispatch radius of 50 miles; and the provider has at least one shift in `SCHEDULED` status whose half-open window, inclusive of `shift_start` and exclusive of `shift_end`, contains the current server clock.

The eligible providers are then ranked by a sequence of keys applied in order. The first key is `rating`, highest first. The second key, breaking ties on rating, is the provider's distance to the breakdown, nearest first. The third key applies only when the call's `service_type` is `TOW`: among providers still tied, those with fewer entries in their `capabilities` list are preferred, favoring specialists for tows; for non-tow calls this key is skipped entirely. The final tie-break is `created_at`, earliest-registered first — never the `id`. When no provider satisfies the eligibility filter, the ranked pool is the empty list, and the operator's recourse is to abandon the call. This read accepts `limit` and `offset` for pagination.

### 3.7. The Dispatch Loop: Offers, Acceptance, and Re-Offer

Dispatch is an offer-and-resolve cycle that keeps a call in `DISPATCHING` while operators try providers one at a time. An operator dispatches an offer to a chosen provider by supplying that `provider_id` together with `expected_service_call_version`. Several conditions must hold for the dispatch to be admitted, and where they fail the error is specific. The call must be in `DISPATCHING`. The target provider must be capable of the requested service: if the provider's `capabilities` do not include the call's `service_type`, the dispatch is rejected with `ERR_CAPABILITY_MISMATCH`. The target provider must be available: if its `status` is not `AVAILABLE`, the dispatch is rejected with `ERR_PROVIDER_UNAVAILABLE`. There must be no live offer already outstanding on the call: if a `DispatchOffer` in `OFFERED` status already exists for this call, the dispatch is rejected with `ERR_OFFER_ALREADY_OUTSTANDING`, because only one offer may be live at a time. The call must not have exhausted its re-offer budget: `dispatch_attempts` must be strictly fewer than the cap of three before another offer is created, and otherwise the dispatch is rejected with `ERR_DISPATCH_LIMIT_REACHED`. Finally, the supplied `expected_service_call_version` must match the call's current `version`, failing which the dispatch is rejected with `ERR_STALE_CALL_VERSION` per §2.7. Among these business rules the capability check precedes the provider-availability check, which precedes the outstanding-offer check, which precedes the attempts-cap check, which precedes the version check.

A successful dispatch creates a `DispatchOffer` in `OFFERED` status — its initial state, with `OFFERED`, `ACCEPTED`, `DECLINED`, and `EXPIRED` the full set and the latter three terminal. The offer records `service_call_id`, `provider_id`, the computed `offer_distance_miles` (haversine from the provider's current location to the breakdown), and the computed `eta_minutes` (§2.5). Creating the offer increments the call's `dispatch_attempts` by one and increments the call's `version` by one. Because each accepted dispatch advances the version, an operator working from a stale view is caught by the OCC check rather than silently issuing a duplicate.

The live offer is resolved one of three ways while the call remains in `DISPATCHING`. The offered provider may accept it, which is the only branch that mutates provider state: acceptance drives a three-hop cascade in which the offer first moves to `ACCEPTED`; because of that, the call moves from `DISPATCHING` to `ASSIGNED` and its `assigned_provider_id` is set to the offer's provider; and because of that, the now-assigned provider moves to `ON_JOB` and its `active_call_id` is set to this call. Acceptance is permitted only when the offer is in `OFFERED`, the acting provider is the offer's provider, the parent call is still `DISPATCHING`, and the provider's `status` is `AVAILABLE`; an unavailable provider at accept time is rejected with `ERR_PROVIDER_UNAVAILABLE`. Acceptance increments the call's `version` by one. Alternatively, the offered provider may decline it: the offer moves to `DECLINED`, the call stays in `DISPATCHING` and is thereby freed for the next offer, and no provider state changes. Or the operator may expire a stale offer: the offer moves to `EXPIRED`, the call again stays in `DISPATCHING` and is freed for the next offer, with no provider state change. Decline and expire are the two non-accepting branches and neither touches provider state, in deliberate contrast to acceptance.

### 3.8. Travel, Completion, and Cost Reconciliation

Once a call is `ASSIGNED`, the assigned provider marks travel begun, advancing the call from `ASSIGNED` to `EN_ROUTE`; this is permitted only when the acting provider is the call's `assigned_provider_id` and the call is `ASSIGNED`, and it increments the call's `version`. From `EN_ROUTE` the provider completes the job, reporting the actual towed distance as `final_towed_miles`; when this value is omitted it defaults to `tow_distance_miles`. Completion is permitted only when the acting provider is the call's `assigned_provider_id` and the call is `EN_ROUTE`. For both `start` and `complete` the ownership check precedes the state check per the §2.9 precedence (ownership fourth, state legality fifth): a provider who is not the call's `assigned_provider_id` is rejected with `ERR_NOT_RESOURCE_OWNER` before state legality is consulted, and because a `DISPATCHING` call has a null `assigned_provider_id` no provider owns it, so a provider invoking `start` or `complete` on a `DISPATCHING` call receives `ERR_NOT_RESOURCE_OWNER` rather than `ERR_INVALID_STATE`.

Completion is also gated by the member's annual quota, evaluated after any annual-period rollover described below: the member's `services_used_this_year` must be strictly fewer than the plan's `annual_service_limit` at the moment of completion. A member whose used count has already reached the limit is rejected with `ERR_ANNUAL_LIMIT_EXCEEDED`. The boundary is inclusive of success up to the limit: a member who has used one fewer than the limit completes successfully and is brought exactly to the limit, whereas a member already at the limit is rejected.

When completion is admitted, the system reconciles cost and quota together. It recomputes `final_cost_cents` using `final_towed_miles` in place of the creation-time estimate, applying the identical base-plus-overage shape and the identical pinned rounding regime of §2.6 — overage mileage beyond the plan's `per_incident_mileage_cap_miles` (never below zero) rounded to three decimals, multiplied by `overage_rate_cents_per_mile`, rounded to whole cents — and sets `member_out_of_pocket_cents` equal to `final_cost_cents`. When `final_towed_miles` is omitted or equals `tow_distance_miles`, the final cost equals the earlier `estimated_cost_cents` and there is no reconciliation delta; when it differs, the final cost diverges from the estimate and that difference is what flows to the member's balance. Before the quota count is read, the system performs the rollover: if the completion timestamp is at or after `annual_period_start` plus 365 days, the system first advances `annual_period_start` by 365 days and resets `services_used_this_year` to 0, and only then evaluates the quota gate. On a successful completion the system increments `services_used_this_year` by one, adds `member_out_of_pocket_cents` to the member's `outstanding_balance_cents`, returns the provider to `AVAILABLE` and clears its `active_call_id`, and increments the call's `version`.

If no provider ever accepts, the operator abandons the call, moving it from `DISPATCHING` to the terminal `UNFULFILLED` state; this is permitted only when the call is `DISPATCHING`, there is no offer currently in `OFFERED`, and at least one dispatch attempt has already been made (`dispatch_attempts` is at least 1). Abandonment increments the call's `version`.

### 3.9. Member Cancellation and Provider Release

A member may cancel its own call while it is still being arranged. Cancellation is permitted from either `DISPATCHING` or `ASSIGNED`, and only by the call's own member. When the call is in `DISPATCHING`, cancellation moves it to `CANCELLED` and, as a conditional cascade, moves any offer currently in `OFFERED` on that call to `EXPIRED`; only the live offer is affected. When the call is in `ASSIGNED`, cancellation drives a two-hop cascade: the call moves to `CANCELLED` and its `assigned_provider_id` is cleared, and because of that the previously assigned provider is released back to `AVAILABLE` with its `active_call_id` cleared — a compensating action that returns the held provider to the pool. Either way, cancellation increments the call's `version`. Attempting to cancel from any other state is rejected as an illegal state change.

### 3.10. Reimbursement Claims and Adjudication

After paying out of pocket on a completed call, a member — or an operator on the member's behalf — files a reimbursement claim. The claim carries `member_id`, `service_call_id` naming the completed call, and `claimed_amount_cents`, the amount the member states it paid, which must be at least 1. At filing time the linked call must belong to the same member and the claimed amount must be at least 1; a claim whose `service_call_id` references a call not owned by the filing member, or whose `claimed_amount_cents` is below 1, is rejected with `ERR_INVALID_CLAIM_TARGET`. A new claim is created in `SUBMITTED` status with `approved_amount_cents` at 0. The lifecycle states are `SUBMITTED`, `UNDER_REVIEW`, `INFO_REQUESTED`, `APPROVED`, and `REJECTED`, with the last two terminal. Claims are fetchable by the owning member or an operator and listable filtered by `member_id`, `service_call_id`, or `status`.

Adjudication is an operator-driven cycle with one member-driven step. An operator begins review, moving the claim from `SUBMITTED` to `UNDER_REVIEW`. From `UNDER_REVIEW` the operator may request more information, moving the claim to `INFO_REQUESTED`; the owning member then supplies it and resubmits, moving the claim from `INFO_REQUESTED` back to `SUBMITTED`, which closes the revision loop `SUBMITTED → UNDER_REVIEW → INFO_REQUESTED → SUBMITTED`. From `UNDER_REVIEW` the operator may instead approve or reject. Approval is permitted only when the claim is `UNDER_REVIEW` and additionally requires the linked call to be `COMPLETED`; a claim whose linked call has not reached `COMPLETED` is rejected with `ERR_CALL_NOT_COMPLETED`. On approval the system sets `approved_amount_cents` to the smaller of the claimed amount and the linked call's `member_out_of_pocket_cents` — the over-claim is trimmed to the documented cost, while a claim at or below the documented cost is approved in full — subtracts `approved_amount_cents` from the member's `outstanding_balance_cents` as the compensating side of the balance invariant, and moves the claim to `APPROVED`. Rejection, also only from `UNDER_REVIEW`, moves the claim to `REJECTED`, leaves `approved_amount_cents` at 0, and leaves the member's `outstanding_balance_cents` unchanged. Each adjudication step — begin-review, request-info, resubmit, approve, and reject — increments the claim's `version`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return a `201 Created` status code. Operations that modify an existing resource, including state transitions and lifecycle actions, return a `200 OK` status code. List and fetch operations return `200 OK`. To reconstruct the full request and response shape for any endpoint, refer to the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/membership-plans` | Create a membership/coverage plan | DispatchOperator |
| GET | `/membership-plans/{id}` | Fetch a plan | DispatchOperator, Member, ServiceProvider |
| GET | `/membership-plans` | List plans (filter by tier) | DispatchOperator, Member, ServiceProvider |
| POST | `/members` | Register a member onto a plan | DispatchOperator |
| GET | `/members/{id}` | Fetch a member | DispatchOperator, Member |
| GET | `/members` | List members (filter by plan or status) | DispatchOperator |
| POST | `/members/{id}/suspend` | Suspend a membership | DispatchOperator |
| POST | `/members/{id}/reinstate` | Reinstate a suspended membership | DispatchOperator |
| POST | `/service-providers` | Register a provider into the network | DispatchOperator |
| GET | `/service-providers/{id}` | Fetch a provider | DispatchOperator, ServiceProvider |
| GET | `/service-providers` | List providers (filter by status) | DispatchOperator, ServiceProvider |
| POST | `/service-providers/{id}/go-offline` | Provider marks itself offline | ServiceProvider |
| POST | `/service-providers/{id}/go-online` | Provider returns to available | ServiceProvider |
| GET | `/service-providers/{id}/offers` | List offers ever sent to this provider | DispatchOperator, ServiceProvider |
| POST | `/service-providers/{id}/shifts` | Schedule an on-call shift window | DispatchOperator, ServiceProvider |
| GET | `/service-providers/{id}/shifts` | List a provider's shifts | DispatchOperator, ServiceProvider |
| POST | `/service-providers/{id}/shifts/{shift_id}/cancel` | Cancel a scheduled shift | DispatchOperator, ServiceProvider |
| POST | `/depots` | Create a tow/repair depot with finite bays | DispatchOperator |
| GET | `/depots/{id}` | Fetch a depot | DispatchOperator, ServiceProvider, Member |
| GET | `/depots` | List depots | DispatchOperator, ServiceProvider, Member |
| POST | `/depots/{id}/bay-reservations` | Reserve a bay at a depot | DispatchOperator |
| GET | `/depots/{id}/bay-reservations` | List a depot's bay reservations | DispatchOperator |
| POST | `/depots/{id}/bay-reservations/{reservation_id}/release` | Release a bay reservation | DispatchOperator |
| POST | `/service-calls` | Member requests roadside assistance | Member, DispatchOperator |
| GET | `/service-calls/{id}` | Fetch a service call | DispatchOperator, Member, ServiceProvider |
| GET | `/service-calls` | List service calls (filter by member or status) | DispatchOperator, Member |
| GET | `/service-calls/{id}/dispatch-candidates` | Ranked eligible provider pool for the call | DispatchOperator |
| POST | `/service-calls/{id}/offers` | Dispatch an offer to a provider (OCC-guarded) | DispatchOperator |
| GET | `/service-calls/{id}/offers` | List offers made for a call | DispatchOperator, Member, ServiceProvider |
| GET | `/service-calls/{id}/bay-reservations` | List bay reservations for this tow call | DispatchOperator, Member |
| POST | `/service-calls/{id}/offers/{offer_id}/accept` | Provider accepts the live offer | ServiceProvider |
| POST | `/service-calls/{id}/offers/{offer_id}/decline` | Provider declines the live offer | ServiceProvider |
| POST | `/service-calls/{id}/offers/{offer_id}/expire` | Operator times out a stale offer | DispatchOperator |
| POST | `/service-calls/{id}/start` | Assigned provider begins travel | ServiceProvider |
| POST | `/service-calls/{id}/complete` | Provider completes the job | ServiceProvider |
| POST | `/service-calls/{id}/abandon` | Operator abandons an unfulfilled call | DispatchOperator |
| POST | `/service-calls/{id}/cancel` | Member cancels their call | Member |
| POST | `/reimbursement-claims` | File a reimbursement claim | Member, DispatchOperator |
| GET | `/reimbursement-claims/{id}` | Fetch a claim | DispatchOperator, Member |
| GET | `/reimbursement-claims` | List claims (filter by member, call, or status) | DispatchOperator, Member |
| POST | `/reimbursement-claims/{id}/begin-review` | Operator starts adjudication | DispatchOperator |
| POST | `/reimbursement-claims/{id}/request-info` | Operator requests more info | DispatchOperator |
| POST | `/reimbursement-claims/{id}/resubmit` | Member resubmits after providing info | Member |
| POST | `/reimbursement-claims/{id}/approve` | Operator approves and credits the member | DispatchOperator |
| POST | `/reimbursement-claims/{id}/reject` | Operator rejects the claim | DispatchOperator |
| POST | `/_clock/set_current_utc` | Pin the server's current UTC clock (test-driving) | DispatchOperator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_MEMBERSHIP_NOT_ACTIVE` | 409 |
| `ERR_CAPABILITY_MISMATCH` | 409 |
| `ERR_PROVIDER_UNAVAILABLE` | 409 |
| `ERR_OFFER_ALREADY_OUTSTANDING` | 409 |
| `ERR_DISPATCH_LIMIT_REACHED` | 409 |
| `ERR_SHIFT_OVERLAP` | 409 |
| `ERR_NO_BAY_AVAILABLE` | 409 |
| `ERR_ANNUAL_LIMIT_EXCEEDED` | 409 |
| `ERR_CALL_NOT_COMPLETED` | 409 |
| `ERR_INVALID_CLAIM_TARGET` | 422 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_PAGINATION` | 422 |
| `ERR_STALE_CALL_VERSION` | 412 |

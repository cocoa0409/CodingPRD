# Airport Meet Assist API — Product Requirements Document

## 1. Introduction

Airports run a quiet economy of care. Every day, passengers who cannot navigate a terminal on their own — wheelchair travellers, unaccompanied minors, seniors making a tight connection — depend on a coordinated hand-off between airline staff, escort agents, and specialized equipment. Today that coordination is stitched together by phone trees and clipboard manifests; requests fall through the cracks, chairs go missing, airlines are billed for escorts that never happened, and families have no way to know whether a minor has actually been handed off at the gate.

This document specifies the **Airport Meet Assist** platform, mounted under `/maa`, a workflow-orchestration API that turns an assist request into a chain of auditable service legs, dispatched agents, checked-out wheelchairs, tracked hand-offs, and settled invoices. The system treats an assist as a first-class business object with two orthogonal state dimensions — a `request_status` lifecycle driven by dispatch and in-field execution, and a `billing_status` lifecycle driven by invoicing and settlement — so that operational failures never silently entangle financial obligations, and financial disputes never silently freeze in-flight care.

Three tensions shape the design. First, **segregation of duties**: the dispatcher who assigns an agent must never be the confirmer who signs off completion, and an unaccompanied minor must be handed off under a second, distinct signature. Second, **posture awareness**: an airport can move from `NORMAL` through `DEGRADED` to `LOCKDOWN`, and every such transition reprices in-flight work, releases equipment, and cancels legs in a controlled cascade. Third, **logical time**: the platform runs on a server-controlled UTC clock so that eligibility windows, shift boundaries, delay surcharges, and stale-request detection are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. A request missing either header, presenting a malformed identifier, or carrying a role outside the enumerated set is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is well-formed but not on the endpoint's authorized-roles list is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The platform recognizes exactly seven roles, spelled as follows:

- `PlatformAdmin` — provisions airports, terminals, flight segments, agents, and wheelchairs, and controls the logical clock.
- `Requester` — creates passengers and assist requests, drafts service legs, and submits or cancels requests.
- `Dispatcher` — dispatches planned legs, running the agent and wheelchair selectors; may also mark no-shows and cancel assignments.
- `Agent` — the airport escort who executes assignments, publishes tracking events, and may open incidents.
- `Confirmer` — a third-party completer of assignments; segregation-of-duties forbids the confirmer from being the dispatcher who assigned the work.
- `OpsManager` — controls airport posture, advances the ops epoch, manages agents, wheelchairs, and incidents, and marks flight segments landed, departed, or cancelled.
- `BillingClerk` — settles invoices through the mark-paid, dispute, resolve-paid, and write-off lifecycle.

Role identity semantics differ across the role set. When `X-User-Role` is `Agent`, `X-User-ID` is the `id` of the acting `Agent` record; ownership checks on any resource that references an agent — most importantly an assignment's `agent_id` — compare that foreign key against `X-User-ID`. When `X-User-Role` is any of `PlatformAdmin`, `Requester`, `Dispatcher`, `Confirmer`, `OpsManager`, or `BillingClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `assigned_by_user_id` on an assignment, as `completed_by_user_id` on a completion, as `umnr_second_signoff_user_id` on a UMNR hand-off, or as `sofia_signoff_by` on the parent assist request — but does not compare it to any entity's `id` for authorization.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, taken from wall-clock UTC; it is independent of the §2.4 logical clock.
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

All list endpoints accept two query parameters, `limit` and `offset`, and return paginated results. The `limit` parameter defaults to **10** and must be an integer between **1** and **100** inclusive; a non-integer `limit`, a `limit` outside that range, a non-integer `offset`, or a negative `offset` is rejected with `ERR_BAD_REQUEST` (HTTP 400). The `offset` parameter defaults to **0**. Sort order is fixed: results are returned in `created_at` ascending order. The response `meta` block for list endpoints carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Logical Time

Almost every persisted entity carries the four common fields: `id` (a server-minted UUID with no type prefix), `created_at` (ISO 8601 UTC with three fractional digits), `updated_at` (refreshed on every mutation), and `version` (an integer that starts at 1 and increments on every mutation). The single exception is `TrackingEvent`, which is append-only: it carries `id` and `created_at` only — both `updated_at` and `version` are absent, because a tracking event is never modified after publication. Entity `created_at` and `updated_at` values are stamped from the logical clock, never from wall-clock.

The server maintains a **logical clock** rather than relying on wall-clock time. At server start, before any clock-override call, the logical clock reads exactly `2026-05-01T00:00:00Z` and must not fall back to wall-clock. A PlatformAdmin-only test-driving capability sets the server's logical clock to a supplied `to_iso8601` instant; this override does not advance any airport's ops epoch and fires no threshold transitions on its own — it is purely a clock override. The override call responds with an object carrying `now_utc`, the new logical time.

Every business comparison that mentions "now" — TSA credential expiry, shift windows, no-show thresholds, stale-request detection, tracking-event timestamps — evaluates against this logical clock.

### 2.5. Airport Posture as a Pricing and Safety Posture

Each airport carries a `posture` field taking one of `NORMAL`, `DEGRADED`, or `LOCKDOWN`, defaulting to `NORMAL` at creation. Posture is simultaneously a pricing input and an operational safety gate, and the OpsManager is the only role permitted to change it.

Posture transitions follow a strict ladder: `NORMAL` may move to `DEGRADED`; `DEGRADED` may move to `LOCKDOWN` or back to `NORMAL`; `LOCKDOWN` may move only back to `NORMAL`. The posture-change call body carries a single `posture` field naming the target posture; requesting the posture the airport already holds, or any transition not on the ladder, is rejected with `ERR_INVALID_STATE` (HTTP 409). Each transition has cascading side effects described in §3.7 — most importantly, moving into `LOCKDOWN` does not merely freeze new work but cancels in-flight legs, releases checked-out chairs, and voids provisional invoices, while moving from `LOCKDOWN` back to `NORMAL` deliberately does **not** auto-revive cancelled legs (a dispatcher must re-book them).

### 2.6. Nested Resource Retrieval and Path Validation

The API exposes a deep resource hierarchy: airports own terminals, flight segments, agents, and wheelchairs; assist requests own service legs, assignments, incidents, and invoices; assignments own tracking events. Path-template identifiers are validated strictly left-to-right. For example, on a request to fetch a terminal under an airport, the airport identifier is resolved first and only then is the terminal resolved within that airport's scope. If any path identifier fails to resolve to a live resource, the request is rejected with `ERR_NOT_FOUND` (HTTP 404). This left-to-right rule applies uniformly across the hierarchy — airport before terminal before segment before leg before assignment.

### 2.7. Optimistic Concurrency Control

Three write endpoints require an explicit expected-version field, which the server compares against the parent entity's current `version` before applying the mutation:

- **AssistRequest lifecycle events.** Posting a `SUBMIT` or `CANCEL` against an assist request requires the request body to carry `expected_assist_request_version` holding the value of the request's `version` field the client last observed. If the version on the server has since advanced — for example because an airport posture change recomputed `provisional_charge_cents` and bumped the version — the request is rejected with `ERR_STALE_VERSION` (HTTP 412).
- **Service-leg dispatch.** Posting a dispatch against a service leg requires the body to carry `expected_assist_request_version` matching the parent assist request's current `version`. If the parent's version has advanced since the dispatcher last read the request, the dispatch is rejected with `ERR_STALE_VERSION` (HTTP 412).
- **Invoice settlement.** Posting `MARK_PAID`, `DISPUTE`, `RESOLVE_PAID`, or `WRITE_OFF` against an invoice requires the body to carry `expected_invoice_version` matching that invoice's current `version`. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not listed above do not take a version field. Mutations on the entities these endpoints touch still bump `version` as a side effect — for instance, posting an assist-request lifecycle event increments the request's `version` by 1, posting an invoice settlement increments the invoice's `version` by 1, and posting an assignment lifecycle event increments the assignment's `version`, the parent service leg's `version`, and the parent assist request's `version` by 1 each. Each cascading status change on the parent request increments its `version` again within the same call, so a dispatch that itself advances the request to `ASSIGNED`, a first `ARRIVE_PICKUP` that advances it to `IN_SERVICE`, or a final `COMPLETE` that finalizes the bill increments the request's `version` by 2 in total.

### 2.8. Monetary Precision and Rounding

All charges in the system are integer **cents**. Every per-leg charge — provisional and final alike — is rounded **half-up to zero decimal places** after applying the tier multiplier and then the posture multiplier, in that order. The rounding happens **per leg**; the request-level total is then the plain sum of the already-rounded per-leg amounts and is never re-rounded at the sum level. The one place a monetary amount is added after rounding is the delay surcharge on the final leg charge, which is appended to the rounded base rather than folded into the pre-rounding computation.

### 2.9. Validation Priority Order

When multiple validation rules guard the same endpoint, the server evaluates them in a fixed priority order so that a more fundamental problem is never masked by a later check:

1. **Authentication** — presence and well-formedness of `X-User-Role` and `X-User-ID` (`ERR_UNAUTHENTICATED`).
2. **Authorization** — the role appears on the endpoint's authorized list (`ERR_UNAUTHORIZED`).
3. **Existence** — path-template identifiers resolve to live resources, left to right (`ERR_NOT_FOUND`).
4. **Optimistic concurrency** — `expected_<parent>_version` matches the parent's current `version` (`ERR_STALE_VERSION`).
5. **State-machine precondition** — the target resource is in the from-state the transition requires (`ERR_INVALID_STATE`).
6. **TSA / regulatory safety** — TSA clearance and UMNR dual-signer requirements (`ERR_TSA_CLEARANCE_REQUIRED`).
7. **Segregation of duties** — dispatcher-versus-confirmer, UMNR third-signer, airline-write-off clerk distinctness (`ERR_SEGREGATION_OF_DUTIES`).
8. **Referential integrity** — foreign keys resolve and respect airport boundaries (`ERR_REFERENTIAL_INTEGRITY`).
9. **Temporal windowing** — shift windows, no future timestamps, no overlapping assignments (`ERR_TEMPORAL_CONFLICT`).
10. **Agent pool capacity** — the agent selector returns a candidate (`ERR_NO_ELIGIBLE_AGENT`).
11. **Wheelchair pool capacity** — the wheelchair selector returns a chair (`ERR_NO_AVAILABLE_WHEELCHAIR`).
12. **Payment-method presence** — the chosen `bill_to` instrument is populated on the passenger (`ERR_PAYMENT_METHOD_REQUIRED`).
13. **Invoice-state guards** — settlement transitions respect the invoice's current status (`ERR_INVOICE_STATE`).
14. **Format and value well-formedness** — the body is a JSON object, enums valid, integers in range, `dob` parses as an ISO date, `iata_code` matches the three-uppercase-letter pattern (`ERR_BAD_REQUEST`).

A useful consequence: a dispatch attempted during `LOCKDOWN` with a stale expected version surfaces `ERR_STALE_VERSION` (priority 4) rather than `ERR_INVALID_STATE` (priority 5) or `ERR_POSTURE_RESTRICTED`, because the OCC check outranks state and posture checks. Guards not enumerated above — `ERR_NO_LEGS`, `ERR_POSTURE_RESTRICTED`, `ERR_ALREADY_IN_SERVICE`, `ERR_CHAIR_IN_USE`, `ERR_WCHC_CHAIR_REQUIRED` — are endpoint-specific and take the order their endpoint sections in §3 give them.

## 3. Business Logic & Workflows

### 3.1. Provisioning the Airport: Terminals, Segments, Agents, and Equipment

Before any passenger can be served, a `PlatformAdmin` provisions the airport itself. Creating an airport requires the `iata_code` (a three-letter code such as `SFO`, globally unique, matching the all-caps three-letter pattern; a malformed or duplicate code is rejected with `ERR_BAD_REQUEST`), the `tz_offset_minutes` offset of airport local time from UTC (for example `-420` for Pacific Daylight Time), and the `meet_buffer_minutes` — the required buffer in minutes between an agent's landing-time and the pick-up, which must be an integer of at least 15 (violations rejected with `ERR_BAD_REQUEST`). The new airport is initialized with `posture` set to `NORMAL` and `ops_epoch` set to zero.

Under the airport, the `PlatformAdmin` creates terminals by supplying a `code` (such as `T1` or `INTL`, unique within the airport; a duplicate code is rejected with `ERR_BAD_REQUEST`) and a `requires_secure_escort` flag; when that flag is true, the terminal is airside-only and any escort through it requires a TSA-cleared agent. The server stamps the new terminal's `airport_id` to the parent airport's `id`, and the new terminal opens with `status` set to `OPEN`; the alternative is `CLOSED`. Flight segments are created with a `flight_no` (carrier flight number such as `UA1234`), a `direction` of either `ARRIVAL` or `DEPARTURE`, the `terminal_id` of the terminal the segment uses (a `terminal_id` that does not resolve, or that resolves to a terminal of another airport, is rejected with `ERR_BAD_REQUEST`), the `scheduled_utc` instant of the scheduled arrival or departure, and an optional `international` boolean flag defaulting to false. Like terminals, segments carry a system-set `airport_id` tying them to the airport at which they depart or arrive. Segments begin in `SCHEDULED` status with `actual_utc` null; once the real arrival or departure is known, an `OpsManager` marks the segment `LANDED`, `DEPARTED`, or `CANCELLED`, supplying `actual_utc` for the former two (omitting it is rejected with `ERR_BAD_REQUEST`). `LANDED` and `DEPARTED` are valid only from `SCHEDULED`; `CANCELLED` is valid from any status other than `CANCELLED` itself — violations are rejected with `ERR_INVALID_STATE`. Cancelling a segment cascades: any `PLANNED` service leg referencing it becomes `CANCELLED`.

Agents are onboarded under an airport with a `display_name`, a `tsa_cleared_until` credential expiry, three boolean certifications — `ummr_certified` for unaccompanied-minor escort, `senior_trained` for senior assistance, and `wc_certified` for pushing WCHC wheelchairs — and the shift window `shift_start_utc` to `shift_end_utc`. The server stamps the agent's `airport_id` to the home airport's `id`. The shift window is validated on creation: the start must be strictly before the end, the shift length may not exceed twelve hours, and a violation is rejected with `ERR_TEMPORAL_CONFLICT`. New agents begin in `ACTIVE` status with `active_assignment_count` and `cumulative_delay_minutes` both zero. Wheelchairs are registered with an `asset_tag` unique within the airport (a duplicate tag is rejected with `ERR_BAD_REQUEST`), a `chair_class` of `MANUAL`, `POWER`, or `BARIATRIC`, and an `is_wchc_rated` flag (accepted as supplied — a `MANUAL` chair flagged WCHC-rated is not rejected at creation, but per §3.4 it is never eligible for a `requires_wchc_chair` leg). The server stamps the chair's `airport_id` to the owning airport's `id`. New chairs start in `AVAILABLE` with `usage_count` zero and `last_maintenance_utc` null; a chair's terminal state is `RETIRED`, reachable only from `MAINTENANCE` and only when no in-flight assignment (in `DISPATCHED`, `AT_PICKUP`, `IN_TRANSIT`, or `AT_GATE`) still references it — attempting retirement while such a reference exists is rejected with `ERR_CHAIR_IN_USE` (HTTP 409). This in-flight-reference check is evaluated before the `MAINTENANCE` from-state precondition, so a retirement attempt that violates both — for example against a `CHECKED_OUT` chair still referenced by an in-flight assignment — is rejected with `ERR_CHAIR_IN_USE` rather than `ERR_INVALID_STATE`. The rest of the chair lifecycle is simple: `SCHEDULE_MAINTENANCE` moves an `AVAILABLE` chair to `MAINTENANCE`, and `COMPLETE_MAINTENANCE` moves a `MAINTENANCE` chair back to `AVAILABLE`, resetting `usage_count` to zero and stamping `last_maintenance_utc` with the current logical clock; either event from any other status is rejected with `ERR_INVALID_STATE`.

### 3.2. The Passenger and the Shape of an Assist Request

A `Requester` (or `PlatformAdmin`) registers each passenger once, capturing `full_name`, `dob` (a strict `YYYY-MM-DD` ISO 8601 date), the `mobility_code` — one of `WCHR` (can walk short distances), `WCHS` (cannot do stairs), or `WCHC` (fully immobile) — and the billing instruments: `airline_pnr` for airline-billed work and `private_card_token` for private-pay work (both optional at registration, defaulting to null). At creation the server derives `passenger_class` from the passenger's `dob` and the logical clock, yielding one of `ADULT`, `SENIOR`, or `UMNR` (unaccompanied minor): the age in full years at the current logical date determines the class — under 18 yields `UMNR`, 65 or older yields `SENIOR`, otherwise `ADULT`. This derived class drives both safety gating and pricing.

With the passenger registered, the `Requester` opens an assist request by supplying the `passenger_id` (an unresolvable passenger id is rejected with `ERR_BAD_REQUEST`), a `bill_to` of `AIRLINE` or `PRIVATE`, a `service_tier` of `STANDARD`, `PRIORITY`, or `CONCIERGE`, an optional `companion_count` (a non-negative integer count of non-passenger companions travelling with the passenger, defaulting to zero), and an optional `umnr_handoff_required` flag (defaulting to false; the flag is stored on the request and gates nothing further on its own). The new request begins in `DRAFT` for `request_status` and `UNBILLED` for `billing_status`, with `provisional_charge_cents` and `final_charge_cents` both unset and `sofia_signoff_by` null.

While the request is in `DRAFT`, the requester adds service legs one at a time. Each leg is anchored to a `segment_id` (an unresolvable segment id is rejected with `ERR_REFERENTIAL_INTEGRITY`, HTTP 422), takes a `leg_kind` of `MEET_ARRIVAL`, `DEPARTURE_ESCORT`, or `CONNECTION_TRANSFER`, plus a `pickup_zone` label (a free-form non-empty string, e.g. curbside or gate), and is stamped by the server with the parent request's `assist_request_id`. For connection chains, the requester may also set `onward_leg_id` pointing at the next leg of the same request — the field is meaningful only for `CONNECTION_TRANSFER` legs, and setting it on any other leg kind, pointing it at another request's leg, or crossing an airport boundary is rejected with `ERR_REFERENTIAL_INTEGRITY` (HTTP 422). At leg creation the server derives several flags and timestamps:

- `scheduled_pickup_utc` is computed as the segment's `scheduled_utc` plus the airport's `meet_buffer_minutes`.
- `requires_wheelchair` is true exactly when the passenger's `mobility_code` is `WCHS` or `WCHC`.
- `requires_wchc_chair` is true exactly when `mobility_code` is `WCHC`.
- `requires_ummr_agent` is true exactly when the passenger's derived class is `UMNR`.
- `requires_senior_agent` is true exactly when the class is `SENIOR`.
- `requires_tsa_escort` is true when the terminal's `requires_secure_escort` flag is set, or when the segment is international and the leg kind is not `MEET_ARRIVAL`.

The new leg begins in `PLANNED` with `actual_pickup_utc`, `completed_utc`, and `final_leg_cents` all null and `provisional_leg_cents` not yet computed. Adding a leg does not mutate the parent assist request — the request's `version` and `updated_at` are left unchanged by leg creation.

### 3.3. Submission and the Forward-Looking Charge

A request in `DRAFT` may be cancelled outright with no side effects, or it may be submitted. Submission is the moment the platform commits to a price estimate, and it enforces five preconditions, each paired with a specific rejection and evaluated in this order. First, the submit is an OCC-guarded write and must carry `expected_assist_request_version`; a mismatch is rejected with `ERR_STALE_VERSION` (per §2.9 this outranks every later check). Second, the request must still be in `DRAFT`; otherwise `ERR_INVALID_STATE`. Third, the request must carry at least one service leg; a submit with zero legs is rejected with `ERR_NO_LEGS` (HTTP 409). Fourth, the chosen billing instrument must be populated: when `bill_to` is `PRIVATE`, the passenger's `private_card_token` must be non-empty, and when `bill_to` is `AIRLINE`, the passenger's `airline_pnr` must be non-empty — violations are rejected with `ERR_PAYMENT_METHOD_REQUIRED` (HTTP 402). Fifth, every leg's segment must sit at an airport whose `posture` is not `LOCKDOWN`; otherwise the operation is rejected with `ERR_POSTURE_RESTRICTED` (HTTP 409).

On successful submission the server computes a **forward-looking provisional charge**, one invocation per service leg. The provisional invoice that results carries an `invoice_kind` of `PROVISIONAL`. The formula for `provisional_leg_cents` proceeds in five steps. Begin with the per-leg base in cents, which is fixed by `leg_kind`: 6000 cents for `MEET_ARRIVAL`, 7500 cents for `DEPARTURE_ESCORT`, and 9500 cents for `CONNECTION_TRANSFER`. Add the applicable flat fees, each in cents: the companion fee is 1500 cents multiplied by the request's `companion_count`; the equipment fee is 1800 cents when the leg requires a WCHC-rated chair, otherwise 800 cents when the leg merely requires a wheelchair, otherwise zero; the UMNR fee is 2500 cents when `requires_ummr_agent` holds; the senior fee is 900 cents when `requires_senior_agent` holds; and the TSA escort fee is 1200 cents when `requires_tsa_escort` holds. Multiply the resulting sum by the tier multiplier — 10000 basis points for `STANDARD`, 12500 for `PRIORITY`, 15000 for `CONCIERGE` — and divide by 10000. Multiply again by the posture multiplier snapshotted from the airport's current posture at compute time — 10000 basis points for `NORMAL`, 12500 for `DEGRADED`, and 10000 again for `LOCKDOWN` (reachable only on recomputation paths, since submission and dispatch are posture-gated) — and divide by 10000. Round the final amount half-up to zero decimal places, yielding integer cents.

The request's `provisional_charge_cents` is then the sum of the per-leg `provisional_leg_cents` over every leg in any non-terminal status — `PLANNED`, `DISPATCHED`, `AT_PICKUP`, `IN_TRANSIT`, `AT_GATE`, or `HANDED_OFF`. The rounding has already happened per leg, so the sum is not re-rounded. Submission then sets `billing_status` to `PROVISIONAL` and creates a `PROVISIONAL` invoice whose `amount_cents` equals the request's `provisional_charge_cents`, whose `bill_to` is copied from the request, whose `status` begins `OPEN`, and whose `created_by_user_id` records the submitting requester's `X-User-ID`. The request's `version` increments by one.

### 3.4. Dispatch: The Agent and Wheelchair Selectors

A `Dispatcher` turns a `PLANNED` leg into actionable work by dispatching it. The dispatch must carry `expected_assist_request_version` matching the parent request's current `version` — a stale view is rejected with `ERR_STALE_VERSION`. Dispatch is permitted only while the parent request is in `SUBMITTED` or `ASSIGNED` and the airport is not in `LOCKDOWN`; attempts outside those states are rejected with `ERR_INVALID_STATE` or `ERR_POSTURE_RESTRICTED` respectively. If the leg `requires_tsa_escort`, at least one candidate agent — `ACTIVE`, within their shift window, and homed at the leg's airport — must hold a `tsa_cleared_until` later than the current logical clock, failing which the dispatch is rejected with `ERR_TSA_CLEARANCE_REQUIRED` (HTTP 409).

The **agent selector** runs as an eligibility filter followed by a deterministic ranking. An agent is eligible when every one of the following holds:

- The agent belongs to the same airport as the leg's segment.
- `status` is `ACTIVE`.
- The current logical clock lies within the agent's shift window, inclusive of both `shift_start_utc` and `shift_end_utc`.
- When the leg `requires_tsa_escort`, the agent's `tsa_cleared_until` is later than now.
- When the leg `requires_ummr_agent`, the agent is `ummr_certified`.
- When the leg `requires_senior_agent`, the agent is `senior_trained`.
- When the leg `requires_wchc_chair`, the agent is `wc_certified`.
- The agent has no overlapping assignment, where overlap is defined below.

Overlap is a half-open interval intersection. An existing assignment of the agent overlaps the candidate leg when the assignment is in `DISPATCHED`, `AT_PICKUP`, `IN_TRANSIT`, or `AT_GATE`, and the half-open interval from its `scheduled_pickup_utc` to its `scheduled_completion_utc` intersects the half-open interval from the leg's `scheduled_pickup_utc` to that time plus the estimated transfer duration. Adjacency — where one interval's end equals the other's start — is **not** a conflict. The estimated transfer duration is fixed by `leg_kind`: 45 minutes for `MEET_ARRIVAL`, 60 minutes for `DEPARTURE_ESCORT`, and 75 minutes for `CONNECTION_TRANSFER`. An agent with an overlapping assignment is excluded; if a dispatcher somehow attempts to force such an assignment the temporal check rejects with `ERR_TEMPORAL_CONFLICT` (HTTP 409).

Eligible agents are ranked by `active_assignment_count` ascending, then by `cumulative_delay_minutes` ascending, then by `shift_start_utc` ascending, then by `created_at` ascending — never by `id`. An empty pool is rejected with `ERR_NO_ELIGIBLE_AGENT` (HTTP 409).

When the leg `requires_wheelchair`, the **wheelchair selector** runs in parallel. A chair is eligible when it belongs to the same airport as the leg's segment, its `status` is `AVAILABLE`, its `usage_count` is below the maintenance interval of 50, and — when the leg `requires_wchc_chair` — the chair is `is_wchc_rated` and its `chair_class` is `POWER` or `BARIATRIC`. Because selection is automatic, a non-qualifying chair is simply never selected; a WCHC leg whose pool holds only non-qualifying chairs fails with `ERR_NO_AVAILABLE_WHEELCHAIR` like any other empty pool, and `ERR_WCHC_CHAIR_REQUIRED` is not raised by dispatch. Chairs are ranked by `usage_count` ascending (prefer less-used equipment), then by `last_maintenance_utc` descending with nulls last, then by `created_at` ascending. An empty wheelchair pool is rejected with `ERR_NO_AVAILABLE_WHEELCHAIR` (HTTP 409).

Successful dispatch creates an `Assignment` in `DISPATCHED` status, records the acting dispatcher's user id as `assigned_by_user_id`, stamps the assignment's `assist_request_id` and `service_leg_id` to the parent request and the leg being dispatched, computes the assignment's `scheduled_completion_utc` as the leg's `scheduled_pickup_utc` plus the leg-kind estimate, mints an opaque `tracking_token` for this assignment, and writes the `agent_id` and (when applicable) `wheelchair_asset_id`. The agent's `active_assignment_count` increments by one. The selected chair transitions from `AVAILABLE` to `CHECKED_OUT` and its `usage_count` increments by one — though if the increment brings `usage_count` to 50, the chair remains `CHECKED_OUT` for the active assignment but becomes ineligible for new checkouts until maintenance completes. When every sibling leg of the parent request is now `DISPATCHED` or later, the parent request's `request_status` advances from `SUBMITTED` to `ASSIGNED`. Dispatch also increments the parent assist request's `version` (by two when the dispatch itself advances the request to `ASSIGNED`; see §2.7).

### 3.5. In-Field Execution: Pickup, Transit, Gate Arrival, and Hand-off

The dispatched `Agent` drives the assignment through a four-stage field workflow. Each lifecycle call carries an `event_type` discriminator naming the transition being attempted (arrive-pickup, depart-pickup, arrive-gate, hand-off, complete, mark-no-show, or cancel-assign). Each event is further restricted to a single role — the four field events (`ARRIVE_PICKUP`, `DEPART_PICKUP`, `ARRIVE_GATE`, `HANDOFF`) to `Agent`, `COMPLETE` to `Confirmer`, and `MARK_NO_SHOW` and `CANCEL_ASSIGN` to `Dispatcher` — and each field event must be against the acting agent's own assignment: the server compares the assignment's `agent_id` to `X-User-ID`, and a wrong role or a foreign assignment is rejected with `ERR_UNAUTHORIZED` (HTTP 403). The four field events are additionally gated on the airport not being in `LOCKDOWN` (`ERR_POSTURE_RESTRICTED`); `COMPLETE`, `MARK_NO_SHOW`, and `CANCEL_ASSIGN` carry no posture gate.

**Arriving at pickup.** The agent's first event moves the assignment (and parent leg) from `DISPATCHED` to `AT_PICKUP`. The leg's `actual_pickup_utc` is stamped with the current logical clock. If the leg `requires_tsa_escort`, the agent's own `tsa_cleared_until` must still be later than now at this moment — an expired clearance is rejected with `ERR_TSA_CLEARANCE_REQUIRED`. When this is the first `AT_PICKUP` across the request's assignments, the parent request advances from `ASSIGNED` to `IN_SERVICE`.

**Departing pickup and arriving at the gate.** The second event moves the pair from `AT_PICKUP` to `IN_TRANSIT`; the third moves them from `IN_TRANSIT` to `AT_GATE`. Neither carries additional preconditions.

**Hand-off.** The hand-off event moves the leg from `AT_GATE` to `HANDED_OFF`. When the leg `requires_ummr_agent`, the payload must carry a `umnr_second_signoff_user_id` — a missing value is rejected with `ERR_SEGREGATION_OF_DUTIES` just like a colliding one — that differs from both the assignment's `assigned_by_user_id` and the acting agent's own user id — the platform enforces a three-way distinctness for unaccompanied minors, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409). The persisted `umnr_second_signoff_user_id` lands on the assignment; the request-level `sofia_signoff_by` field records the agent user id who performed the first sign-off when applicable.

**Completion.** A `Confirmer` — never the dispatcher who assigned the work — closes the leg from `HANDED_OFF` to `COMPLETED`. The confirmer's user id must differ from `assigned_by_user_id`; otherwise the completion is rejected with `ERR_SEGREGATION_OF_DUTIES`. On success, the assignment's `completed_by_user_id` is stamped with `X-User-ID`. The checked-out chair returns from `CHECKED_OUT` to `AVAILABLE`, unless its `usage_count` has reached 50, in which case it transitions instead into `MAINTENANCE`. The agent's `active_assignment_count` decrements by one, and the agent's `cumulative_delay_minutes` accumulates the non-negative difference, truncated down to whole minutes, between the actual completion instant and the assignment's `scheduled_completion_utc` — that is, zero when the work finished early or on time, and the overrun in whole minutes otherwise. The leg's `completed_utc` is stamped and its `final_leg_cents` is computed by the chronological formula of §3.6.

Completion carries two further cascades. If the leg is a `CONNECTION_TRANSFER` with `onward_leg_id` set, and the onward leg is not already terminal (`CANCELLED`, `FAILED`, `COMPLETED`, or `NO_SHOW`), the onward leg's `scheduled_pickup_utc` is recomputed as the later of its current value and the just-completed leg's `completed_utc` plus the onward airport's `meet_buffer_minutes`, and the onward leg's `provisional_leg_cents` is recomputed using the new pickup time and the airport's current posture; only the onward leg's own fields change — the request-level `provisional_charge_cents` is not recomputed here. And when every sibling leg of the parent request has reached `COMPLETED`, the parent request advances from `IN_SERVICE` to `COMPLETED`, triggering finalization of the bill as described in §3.6.

### 3.6. Finalization: The Chronological Charge and Invoice Settlement

The provisional charge of §3.3 is a forward-looking estimate; the final charge is a chronological recomputation that replaces scheduled inputs with actual ones. The **final leg charge** uses the identical base — leg-kind base, companion fee, equipment fee, UMNR fee, senior fee, TSA fee, tier multiplier, posture multiplier, half-up rounding to integer cents — but with two substitutions: the segment's `actual_utc` replaces its `scheduled_utc`, and the airport's posture **at the moment of completion** replaces the posture snapshot from submit time. On top of the rounded base, a **delay surcharge** is appended: the delay in minutes is the non-negative difference between `actual_utc` and `scheduled_utc`, truncated down to whole minutes; a grace of 20 minutes is subtracted; any positive remainder is charged at 75 cents per minute. The surcharge is added **after** the rounding — it is not folded into the pre-rounding multiplication.

The request's `final_charge_cents` is the sum of per-leg `final_leg_cents` over every leg in a non-`CANCELLED` status, again without any re-rounding at the sum level.

When the parent request rolls into `COMPLETED` — every leg in `COMPLETED` and `billing_status` not `DISPUTED` — the server sets `billing_status` to `FINALIZED`, computes `final_charge_cents`, and issues a `FINAL` invoice whose `amount_cents` equals that total, whose `supersedes_invoice_id` points at the earlier `PROVISIONAL` invoice, and whose arrival transitions that provisional invoice from `OPEN` to `VOID`.

From `FINALIZED`, a `BillingClerk` settles the invoice through one of four events. `MARK_PAID` is valid only on a `FINAL` invoice — a provisional invoice is never directly payable — and moves both the invoice and the parent request's `billing_status` to `PAID`. `DISPUTE` moves any `OPEN` invoice — the guard checks status only, so even an `OPEN` provisional invoice may be disputed — and the parent's `billing_status` to `DISPUTED`; this does **not** roll back `request_status` — the dispute blocks only the settlement step. From `DISPUTED`, the clerk may `RESOLVE_PAID` to reach `PAID`, or `WRITE_OFF` to reach `WRITTEN_OFF`. Settlement-state violations — marking a provisional invoice paid, disputing an invoice not `OPEN`, resolving or writing off an invoice not `DISPUTED` — are rejected with `ERR_INVOICE_STATE` (HTTP 409).

Airline write-offs carry an additional segregation-of-duties rule and an audit requirement. When `bill_to` is `AIRLINE`, the clerk performing the write-off must differ from the `created_by_user_id` recorded on the request's original provisional invoice — the submitting requester's user id (§3.3) — a self-write-off is rejected with `ERR_SEGREGATION_OF_DUTIES`. Independently of who signs it, every write-off against a `FINAL` invoice recomputes the same final-leg-charge formula with the posture multiplier pinned to the `NORMAL` value of 10000 basis points; the resulting cents value — which differs from the FINAL amount whenever the actual posture was not `NORMAL` — is the **write-off baseline**, recorded on the invoice's `writeoff_baseline_cents` field for audit even though the written-off amount itself equals the existing invoice's `amount_cents`. All four settlement events are OCC-guarded by `expected_invoice_version`.

### 3.7. Posture Changes and the Ops Epoch

Airport posture transitions, governed by the ladder of §2.5, have request-wide financial and operational consequences.

- **NORMAL → DEGRADED.** Every assist request at this airport whose `request_status` is `SUBMITTED` or `ASSIGNED` has its `provisional_charge_cents` recomputed with the `DEGRADED` multiplier of 1.25 (12500 basis points), and each such request's `version` increments.
- **DEGRADED → NORMAL.** The same set of requests is recomputed with the `NORMAL` multiplier of 1.00 (10000 basis points).
- **DEGRADED → LOCKDOWN.** Every service leg at this airport in `PLANNED`, `DISPATCHED`, or `AT_PICKUP` transitions to `CANCELLED`. Each cancelled leg bubbles up: when every leg of a request is in `CANCELLED` or `FAILED`, the parent request's `request_status` becomes `FAILED`, its provisional invoice (if any) is voided, and `billing_status` returns to `UNBILLED`. In-flight assignments (in `DISPATCHED`, `AT_PICKUP`, `IN_TRANSIT`, or `AT_GATE`) belonging to a cancelled leg are themselves `CANCELLED`, each decrementing its agent's `active_assignment_count` by one, and wheelchairs in `CHECKED_OUT` whose assignment's leg was just cancelled return to `AVAILABLE` without decrementing `usage_count`.
- **LOCKDOWN → NORMAL.** No auto-revival: legs cancelled by the lockdown remain cancelled and a dispatcher must re-book them.

Separately from posture, an `OpsManager` may advance the airport's **ops epoch**. Each call increments `ops_epoch` by one and then applies three threshold transitions scoped to the airport. Any agent whose `shift_end_utc` is now in the past and whose status is still `ACTIVE` transitions to `OFF_SHIFT`, firing the same unassign cascade as a suspend: their in-flight assignments in `DISPATCHED`, `AT_PICKUP`, or `IN_TRANSIT` become `CANCELLED`, each cancellation returns its parent leg to `PLANNED` (with `scheduled_pickup_utc` unchanged), and any chair those assignments held returns from `CHECKED_OUT` to `AVAILABLE` without decrementing `usage_count`. Any assignment in `DISPATCHED` whose `scheduled_pickup_utc` is now more than 30 minutes in the past is marked `NO_SHOW`, releasing its chair to `AVAILABLE` without decrementing `usage_count` and decrementing the agent's `active_assignment_count`; when every other leg of the parent request is already terminal (`COMPLETED`, `NO_SHOW`, `CANCELLED`, or `FAILED`), the parent leg is also marked `NO_SHOW` and the request transitions to `FAILED`, voiding its provisional invoice (if any) and returning `billing_status` from `PROVISIONAL` to `UNBILLED`. And any assist request that has remained in `SUBMITTED` unchanged through two consecutive ops-epoch ticks transitions to `FAILED` as stale — concretely, submission snapshots the airport's `ops_epoch` at submit time, and the request fails once the airport's epoch has advanced by two or more beyond that snapshot; a stale failure likewise voids the provisional invoice (if any) and returns `billing_status` from `PROVISIONAL` to `UNBILLED`.

### 3.8. Incidents, Suspension, and Adjustments

Anyone on the ground — an `Agent`, an `OpsManager`, or a `Dispatcher` — may open an incident against an assignment, supplying the `assignment_id` (an unresolvable assignment id is rejected with `ERR_BAD_REQUEST`), a `kind` of `FALL`, `MISSED_CONNECTION`, `MEDICAL`, `PROPERTY_DAMAGE`, or `SECURITY`, a `severity` of `MINOR`, `MAJOR`, or `CRITICAL`, and free-text `description`. The server stamps the new incident with the parent request's `assist_request_id`. The new incident begins `OPEN` with `opened_at_utc` stamped by the server. An `OpsManager` acknowledges an `OPEN` incident, moving it to `ACKED`, and resolves an `ACKED` incident, moving it to `RESOLVED`.

Resolution of a `CRITICAL` incident fires two cascades. First, when the linked assignment's agent is `ACTIVE`, that agent transitions to `SUSPENDED` and the full unassign cascade of §3.7 fires: in-flight assignments become `CANCELLED`, their parent legs return to `PLANNED`, and held chairs return to `AVAILABLE` without decrementing `usage_count`. The same cascade runs when an `OpsManager` explicitly suspends an agent — suspension is valid only from `ACTIVE`, and reinstatement only from `SUSPENDED`, violations rejected with `ERR_INVALID_STATE` — and the reverse transition, reinstatement from `SUSPENDED` back to `ACTIVE`, has no side effects. Second, when a `CRITICAL` incident is of kind `PROPERTY_DAMAGE` and the parent request's `billing_status` is `FINALIZED`, the server creates an `ADJUSTMENT` invoice crediting twenty percent of the request's `final_charge_cents` — the credit is rounded to the nearest whole cent and carried as a negative `amount_cents` — with `supersedes_invoice_id` pointing at the final invoice; if that final invoice is still `OPEN`, it transitions to `VOID`.

### 3.9. Tracking the Work

While an assignment is in flight, the assigned `Agent` publishes tracking events by presenting the assignment's opaque `tracking_token`, along with an `event_kind` of `LOCATION_PING`, `PICKUP_CONFIRM`, `GATE_ARRIVAL`, `HANDOFF_START`, or `HANDOFF_COMPLETE`, optional `lat` and `lon` coordinates (required in practice only for location pings), and the `occurred_at_utc` instant at which the event happened. The server resolves the token to the underlying assignment — an unresolvable token is rejected with `ERR_BAD_REQUEST` — and stamps the event's `assignment_id` accordingly; possession of the token alone authorizes publication, with no further comparison of `X-User-ID` against the assignment's `agent_id`. The server rejects any event whose `occurred_at_utc` lies in the future with `ERR_TEMPORAL_CONFLICT`. Tracking events are append-only — they carry `id` and `created_at` but no `version` and no `updated_at` — and are listed back in chronological order against the assignment.

### 3.10. Cancellation, No-Shows, and the Segregation Lattice

A `Requester` may cancel an assist request in `DRAFT` with no side effects. Cancelling a `SUBMITTED` request is permitted only when no assignment has reached `AT_PICKUP`, `IN_TRANSIT`, or `AT_GATE`; attempting to cancel with such an in-flight assignment is rejected with `ERR_ALREADY_IN_SERVICE` (HTTP 409). The in-flight-assignment check is evaluated before the request-state gate, so the rejection is `ERR_ALREADY_IN_SERVICE` even when the in-flight assignment has already advanced the parent request to `IN_SERVICE` (per §3.5). A successful cancellation of a submitted request cascades: every `DISPATCHED` assignment becomes `CANCELLED` and releases its chair to `AVAILABLE` without decrementing `usage_count`, each released agent's `active_assignment_count` decrements by one, the provisional invoice (if any) is voided, and `billing_status` returns to `UNBILLED`. The parent legs that were `PLANNED` or `DISPATCHED` become `CANCELLED`.

A `Dispatcher` may also mark a `DISPATCHED` assignment as `NO_SHOW` once the current logical clock is more than 30 minutes past the leg's `scheduled_pickup_utc` — attempting it earlier violates the temporal rule and is rejected with `ERR_INVALID_STATE`. The chair returns to `AVAILABLE` (without decrementing `usage_count`), the agent's `active_assignment_count` decrements, and when every other leg of the parent request is already terminal, the leg itself is marked `NO_SHOW` and the request transitions to `FAILED`, voiding its provisional invoice (if any) and returning `billing_status` from `PROVISIONAL` to `UNBILLED`; while any sibling leg remains non-terminal, the no-showed leg simply stays `DISPATCHED`. A dispatcher may also directly cancel a `DISPATCHED` assignment; in that case the parent leg transitions to `CANCELLED` (not back to `PLANNED`), distinguishing the direct cancel from the agent-suspend cascade which leaves the leg rebookable in `PLANNED`; if that leaves every leg of the request in `CANCELLED` or `FAILED`, the request bubbles to `FAILED` exactly as in §3.7 (provisional invoice voided, `billing_status` back to `UNBILLED`).

The platform's segregation lattice is worth restating as a single rule of thumb. The user who dispatches an assignment may not confirm its completion; the user who signs a UMNR hand-off second must differ from both the dispatcher and the acting agent; and the clerk who writes off an airline-billed invoice must differ from the clerk who created the provisional invoice. Violations in all three directions are rejected with `ERR_SEGREGATION_OF_DUTIES`.

## 4. Endpoint Definitions

All endpoints are mounted under the `/maa` prefix. Endpoints that create a new resource return HTTP 201; endpoints that modify an existing resource or list resources return HTTP 200. Authentication, authorization, existence, optimistic-concurrency, state, safety, segregation, referential, temporal, capacity, fiscal, and format validations apply as described in §2.9, in that priority order.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/maa/airports` | Create an Airport | `PlatformAdmin` |
| GET | `/maa/airports/{id}` | Fetch an Airport | `PlatformAdmin`, `OpsManager`, `Dispatcher`, `Agent`, `Confirmer`, `Requester`, `BillingClerk` |
| POST | `/maa/airports/{id}/posture` | Change airport posture; cascades to in-flight requests | `OpsManager` |
| POST | `/maa/airports/{id}/run_ops` | Advance airport ops_epoch; fire threshold transitions | `OpsManager` |
| POST | `/maa/airports/{id}/terminals` | Create a Terminal under an Airport | `PlatformAdmin` |
| GET | `/maa/airports/{id}/terminals` | List Terminals under an Airport | `PlatformAdmin`, `OpsManager`, `Dispatcher`, `Agent`, `Confirmer`, `Requester`, `BillingClerk` |
| GET | `/maa/terminals/{id}` | Fetch a single Terminal | `PlatformAdmin`, `OpsManager`, `Dispatcher`, `Agent`, `Confirmer`, `Requester`, `BillingClerk` |
| GET | `/maa/terminals/{id}/segments` | List FlightSegments that use this Terminal | `PlatformAdmin`, `OpsManager`, `Dispatcher`, `Agent`, `Confirmer`, `Requester`, `BillingClerk` |
| POST | `/maa/airports/{id}/segments` | Create a FlightSegment | `PlatformAdmin` |
| GET | `/maa/airports/{id}/segments` | List FlightSegments (filterable by `direction`, `status`, `terminal_id`) | `PlatformAdmin`, `OpsManager`, `Dispatcher`, `Agent`, `Confirmer`, `Requester`, `BillingClerk` |
| GET | `/maa/segments/{id}` | Fetch a single FlightSegment | `PlatformAdmin`, `OpsManager`, `Dispatcher`, `Agent`, `Confirmer`, `Requester`, `BillingClerk` |
| GET | `/maa/segments/{id}/legs` | List ServiceLegs that reference this FlightSegment | `PlatformAdmin`, `OpsManager`, `Dispatcher`, `Agent`, `Confirmer`, `Requester`, `BillingClerk` |
| POST | `/maa/segments/{id}/events` | Mark a FlightSegment LANDED / DEPARTED / CANCELLED with `actual_utc` | `OpsManager` |
| POST | `/maa/passengers` | Create a Passenger | `Requester`, `PlatformAdmin` |
| GET | `/maa/passengers/{id}` | Fetch a Passenger | `PlatformAdmin`, `OpsManager`, `Dispatcher`, `Agent`, `Confirmer`, `Requester`, `BillingClerk` |
| POST | `/maa/airports/{id}/agents` | Create an Agent under an Airport | `PlatformAdmin` |
| GET | `/maa/airports/{id}/agents` | List Agents at an Airport (filterable by `status`) | `PlatformAdmin`, `OpsManager`, `Dispatcher`, `BillingClerk` |
| GET | `/maa/agents/{id}` | Fetch an Agent | `PlatformAdmin`, `OpsManager`, `Dispatcher`, `Agent`, `Confirmer`, `BillingClerk` |
| GET | `/maa/agents/{id}/assignments` | List Assignments currently referencing this Agent | `PlatformAdmin`, `OpsManager`, `Dispatcher`, `BillingClerk` |
| POST | `/maa/agents/{id}/events` | Agent lifecycle events (SUSPEND, REINSTATE); `reason` is optional | `OpsManager` |
| POST | `/maa/airports/{id}/wheelchairs` | Create a WheelchairAsset | `PlatformAdmin` |
| GET | `/maa/airports/{id}/wheelchairs` | List WheelchairAssets at an Airport (filterable by `status`, `chair_class`) | `PlatformAdmin`, `OpsManager`, `Dispatcher`, `BillingClerk` |
| GET | `/maa/wheelchairs/{id}` | Fetch a WheelchairAsset | `PlatformAdmin`, `OpsManager`, `Dispatcher`, `BillingClerk` |
| GET | `/maa/wheelchairs/{id}/assignments` | List Assignments referencing this WheelchairAsset | `PlatformAdmin`, `OpsManager`, `Dispatcher`, `BillingClerk` |
| POST | `/maa/wheelchairs/{id}/events` | Wheelchair lifecycle events (SCHEDULE_MAINTENANCE, COMPLETE_MAINTENANCE, RETIRE); `note` is optional | `OpsManager` |
| POST | `/maa/assist-requests` | Create an AssistRequest in DRAFT | `Requester` |
| GET | `/maa/assist-requests/{id}` | Fetch an AssistRequest | `PlatformAdmin`, `OpsManager`, `Dispatcher`, `Agent`, `Confirmer`, `Requester`, `BillingClerk` |
| GET | `/maa/assist-requests` | List AssistRequests (filterable by `passenger_id`, `request_status`, `billing_status`) | `PlatformAdmin`, `OpsManager`, `Dispatcher`, `BillingClerk` |
| POST | `/maa/assist-requests/{id}/legs` | Add a ServiceLeg to a DRAFT AssistRequest | `Requester` |
| GET | `/maa/assist-requests/{id}/legs` | List ServiceLegs of an AssistRequest | `PlatformAdmin`, `OpsManager`, `Dispatcher`, `Agent`, `Confirmer`, `Requester`, `BillingClerk` |
| GET | `/maa/legs/{id}` | Fetch a ServiceLeg | `PlatformAdmin`, `OpsManager`, `Dispatcher`, `Agent`, `Confirmer`, `Requester`, `BillingClerk` |
| GET | `/maa/legs/{id}/onward-legs` | List ServiceLegs whose `onward_leg_id` equals this leg | `PlatformAdmin`, `OpsManager`, `Dispatcher`, `Agent`, `Confirmer`, `Requester`, `BillingClerk` |
| POST | `/maa/assist-requests/{id}/events` | AssistRequest lifecycle (SUBMIT, CANCEL); body must include `expected_assist_request_version`; `note` is optional | `Requester` |
| POST | `/maa/legs/{id}/dispatch` | Dispatch a PLANNED ServiceLeg; body must include `expected_assist_request_version` | `Dispatcher` |
| GET | `/maa/assignments/{id}` | Fetch an Assignment | `PlatformAdmin`, `OpsManager`, `Dispatcher`, `Agent`, `Confirmer`, `BillingClerk` |
| GET | `/maa/assignments/{id}/incidents` | List Incidents referencing this Assignment | `PlatformAdmin`, `OpsManager`, `Dispatcher`, `Agent`, `Confirmer`, `BillingClerk` |
| GET | `/maa/assist-requests/{id}/assignments` | List Assignments under an AssistRequest | `PlatformAdmin`, `OpsManager`, `Dispatcher`, `Agent`, `Confirmer`, `Requester`, `BillingClerk` |
| GET | `/maa/legs/{id}/assignments` | List Assignments for a ServiceLeg | `PlatformAdmin`, `OpsManager`, `Dispatcher`, `Agent`, `Confirmer`, `BillingClerk` |
| POST | `/maa/assignments/{id}/events` | Assignment lifecycle events (ARRIVE_PICKUP, DEPART_PICKUP, ARRIVE_GATE, HANDOFF, COMPLETE, MARK_NO_SHOW, CANCEL_ASSIGN); `umnr_second_signoff_user_id` and `note` are optional | `Agent`, `Confirmer`, `Dispatcher` |
| POST | `/maa/incidents` | Open an Incident against an Assignment | `Agent`, `OpsManager`, `Dispatcher` |
| GET | `/maa/incidents/{id}` | Fetch an Incident | `PlatformAdmin`, `OpsManager`, `Dispatcher`, `Agent`, `Confirmer`, `BillingClerk` |
| GET | `/maa/assist-requests/{id}/incidents` | List Incidents under an AssistRequest | `PlatformAdmin`, `OpsManager`, `Dispatcher`, `Agent`, `Confirmer`, `BillingClerk` |
| POST | `/maa/incidents/{id}/events` | Incident lifecycle (ACK, RESOLVE); `note` is optional | `OpsManager` |
| GET | `/maa/invoices/{id}` | Fetch an Invoice | `PlatformAdmin`, `OpsManager`, `BillingClerk`, `Requester` |
| GET | `/maa/invoices/{id}/adjustments` | List ADJUSTMENT invoices whose `supersedes_invoice_id` equals this invoice | `PlatformAdmin`, `OpsManager`, `BillingClerk` |
| GET | `/maa/assist-requests/{id}/invoices` | List Invoices of an AssistRequest | `PlatformAdmin`, `OpsManager`, `BillingClerk`, `Requester` |
| POST | `/maa/invoices/{id}/events` | Invoice settlement lifecycle (MARK_PAID, DISPUTE, RESOLVE_PAID, WRITE_OFF); body must include `expected_invoice_version`; `note` is optional | `BillingClerk` |
| POST | `/maa/tracking` | Publish a TrackingEvent identified by `tracking_token` | `Agent` |
| GET | `/maa/assignments/{id}/tracking` | List TrackingEvents of an Assignment (chronological) | `PlatformAdmin`, `OpsManager`, `Dispatcher`, `Agent`, `Confirmer`, `BillingClerk` |
| POST | `/maa/_clock/set_current_utc` | Set the server's logical clock to `to_iso8601` | `PlatformAdmin` |

## 5. Error Code Catalogue

Trigger conditions for each error are described in §2 and §3; the table below is the canonical identifier-to-status mapping.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_BAD_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_NO_LEGS` | 409 |
| `ERR_PAYMENT_METHOD_REQUIRED` | 402 |
| `ERR_TSA_CLEARANCE_REQUIRED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_REFERENTIAL_INTEGRITY` | 422 |
| `ERR_TEMPORAL_CONFLICT` | 409 |
| `ERR_NO_ELIGIBLE_AGENT` | 409 |
| `ERR_NO_AVAILABLE_WHEELCHAIR` | 409 |
| `ERR_INVOICE_STATE` | 409 |
| `ERR_ALREADY_IN_SERVICE` | 409 |
| `ERR_CHAIR_IN_USE` | 409 |
| `ERR_WCHC_CHAIR_REQUIRED` | 409 |
| `ERR_POSTURE_RESTRICTED` | 409 |

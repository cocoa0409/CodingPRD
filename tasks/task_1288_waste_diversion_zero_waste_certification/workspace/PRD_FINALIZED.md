# Waste Diversion & Zero-Waste Certification API — Product Requirements Document

## 1. Introduction

Facilities pursuing zero-waste certification live and die by their diversion data: hauler weight tickets, contamination observations, characterization audits, and the rebate and tipping-fee economics that ride on top of them. Today that evidence arrives as paper tickets and spreadsheets, and the distance between what a site claims and what a reviewer can verify is exactly where certification programs lose credibility. A credible program needs a system of record in which every certified figure is derived from validated evidence rather than self-reported claims.

This document specifies the Waste Diversion & Zero-Waste Certification API, the backbone of a facility sustainability program. It governs the full chain of custody of diversion data — site enrollment, vendor registration, contract negotiation with rebate and penalty terms, weight-ticket intake and data stewardship, contamination monitoring with corrective training, site goal tracking, scorecard periods, and the certification application workflow that culminates in a `BRONZE`, `SILVER`, `GOLD`, or `ZERO_WASTE` award. Throughout, the system enforces segregation of duties between the people who submit data, the people who validate it, and the people who certify it, and it keeps live operational numbers strictly separate from the certified numbers that justify an award.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, formats, and guarantees that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which names their operational capacity. The system recognizes five roles, spelled exactly as follows: `SustainabilityManager`, `VendorUser`, `DataSteward`, `WasteAuditor`, and `CertificationOfficer`. A request with a missing header, or whose role is not one of these declared values, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted to call the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

Role identity is defined as follows. When `X-User-Role` is `VendorUser`, `X-User-ID` is the `id` of the acting `Vendor`; ownership checks on any resource that references a `Vendor` compare the resource's `vendor_id` field to `X-User-ID`, and a mismatch on ticket operations is rejected with `ERR_VENDOR_MISMATCH` (HTTP 403). When `X-User-Role` is `SustainabilityManager`, `DataSteward`, `WasteAuditor`, or `CertificationOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example, as `submitted_by` on a certification application at submit time or as `decided_by` at decision time — but it never compares it to any entity's `id`.

Read access is broad: all five roles may retrieve any resource through the list and detail endpoints. Write privileges are narrow and scoped per role, as described in §3 and summarized in §4.

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

List endpoints paginate through two query parameters. `limit` sets the maximum number of items returned; when omitted it defaults to 10, and it accepts values from a minimum of 1 to a maximum of 100. `offset` sets the number of items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order. The `meta` object of list responses carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity and Mutation Semantics

Every primary resource in the program — sites, vendors, contracts, tickets, contamination events, goals, scorecard periods, and certification applications — carries a standard set of system-managed properties: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits captured at creation; `updated_at`, a timestamp of the same format refreshed on any change to the resource; and `version`, an integer that increments by one on every mutation. The waste audit is the single exception: as an immutable measurement log it carries only `id` and `created_at`, both `updated_at` and `version` are absent, and it exposes no update or delete capability once recorded.

Mutations that a workflow performs on a resource's computed fields count as mutations of that resource. When ticket activity moves a scorecard period's totals, for example, the period's `updated_at` refreshes and its `version` increments, exactly as if a client had edited the period directly.

### 2.5. The Program's Logical Clock

Every date-sensitive rule in the program — the rejection of future-dated tickets, contract expiry, the twelve-month certification lapse — evaluates against a server-maintained logical clock, never against wall-clock time. Before any clock operation has been performed, the logical clock reads exactly 2026-08-01T00:00:00Z. A `CertificationOfficer` advances it through a test-driving capability that takes a `to_iso8601` timestamp and returns the new clock value as `current_utc`. The logical clock never moves backward, and it never falls back to wall-clock time under any circumstance.

### 2.6. Weights, Measures, and Rounding Discipline

Scale weights are integer pounds throughout the system, and tonnage conversions use exactly 2,000 pounds per short ton, dividing pounds by 2,000 as an exact decimal with no intermediate rounding. Diversion rates are percentages carried to exactly 2 decimal places, rounded half up. All monetary figures — rebates, penalties, settlements, and cost avoidance — are integer cents produced by round-half-up rounding; where a total is built from per-ticket amounts, each ticket's amount is rounded to cents first and only then summed (see §3.7). Contamination percentages accept values from 0 to 100 inclusive.

### 2.7. Optimistic Concurrency on Application Creation

Drafting a certification application is the only operation in the API guarded by optimistic concurrency control. A `POST /certification_applications` request must carry `expected_site_version`, the applicant's last-observed `version` of the target site. If the site's current `version` has advanced since that observation, the create is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the site before retrying. The guard exists because a successful draft creation legitimately supersedes an existing draft of the same site and level (see §3.8): a writer holding a stale site version would otherwise withdraw a draft it never saw. No endpoint other than application creation accepts a version field.

### 2.8. The Request Validation Pipeline

Every request passes through an ordered pipeline of validation layers, and a failure in an earlier layer surfaces before any later check is evaluated. The layers, in order, are:

1. **Authentication** — the `X-User-ID` and `X-User-Role` headers are present and the role is a declared role; otherwise `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Authorization and vendor ownership** — the role is permitted on the endpoint (`ERR_FORBIDDEN`, HTTP 403), and for a `VendorUser` the body or path `vendor_id` equals `X-User-ID` (`ERR_VENDOR_MISMATCH`, HTTP 403).
3. **Payload well-formedness** — required fields are present, no unknown fields are supplied, enum values belong to their declared sets, and numeric ranges hold (a `contamination_pct` between 0 and 100, weights as positive integers); violations yield `ERR_INVALID_REQUEST` (HTTP 400).
4. **Existence** — path identifiers and body foreign keys resolve to existing resources, with path identifiers checked left to right; the first missing resource yields `ERR_NOT_FOUND` (HTTP 404).
5. **Optimistic concurrency** — on application creation, `expected_site_version` must equal the site's current `version`; otherwise `ERR_STALE_VERSION` (HTTP 412).
6. **Target-state legality** — the target resource's own state must permit the requested transition, with state-specific rejections such as `ERR_TICKET_NOT_PENDING`, `ERR_TICKET_NOT_REJECTED`, `ERR_TICKET_NOT_VALIDATED`, `ERR_APPLICATION_NOT_DRAFT`, `ERR_APPLICATION_NOT_SUBMITTED`, `ERR_APPLICATION_NOT_IN_REVIEW`, or the generic `ERR_INVALID_STATE` (all HTTP 409).
7. **Compliance gates** — segregation of duties on decisions (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403) and the probation gate on submission (`ERR_STANDING_PROBATION`, HTTP 409).
8. **Uniqueness, overlap, and payload-internal consistency** — duplicate ticket references, overlapping contract or goal windows, weight arithmetic, and stream-to-contract agreement; mostly HTTP 409, with `ERR_INVALID_WEIGHTS` and `ERR_STREAM_CONTRACT_MISMATCH` at HTTP 422.
9. **Cross-entity state and scope** — referenced contracts and vendors being `ACTIVE`, reporting periods being `CLOSED`, and foreign-key scope agreement (`ERR_CROSS_SITE_REFERENCE` is HTTP 422; the rest are HTTP 409).
10. **Window validity and clock** — window ordering rules (`ERR_WINDOW_INVALID`, HTTP 422), future-dated tickets (`ERR_TICKET_DATE_FUTURE`, HTTP 422), and open-period containment (`ERR_NO_OPEN_PERIOD`, HTTP 409).
11. **Fiscal and performance gates** — the rebate-rate policy cap and the certification threshold (`ERR_REBATE_RATE_CAP_EXCEEDED` and `ERR_CERTIFICATION_THRESHOLD_NOT_MET`, both HTTP 422).

Within period creation, one ordering refinement applies inside the overlap layer: the single-open-period guard fires first, so a site that already has an `OPEN` period yields `ERR_PERIOD_ALREADY_OPEN` rather than `ERR_PERIOD_OVERLAP`.

### 2.9. Referential Scope and Path Resolution

Requests that address nested or referenced resources resolve identifiers in a strict left-to-right order: the request is rejected immediately with the 404 error corresponding to the first identifier that does not name an existing resource, before any later identifier or business rule is examined. Beyond existence, foreign keys must agree in scope. A ticket must reference a contract that belongs to the ticket's own site and vendor; a contamination event's linked ticket must belong to the event's site; an application's reporting period must belong to the applicant site. Scope violations are rejected with `ERR_CROSS_SITE_REFERENCE` (HTTP 422). Detail resources are addressed by their own identifiers — `site_id`, `vendor_id`, `contract_id`, `ticket_id`, `audit_id`, `event_id`, `goal_id`, `period_id`, and `application_id` — in the paths enumerated in §4.

## 3. Business Logic & Workflows

### 3.1. Enrolling Sites and Registering Vendors

A `SustainabilityManager` brings a facility into the program by supplying its display `name` and two fiscal policy figures: `landfill_tip_fee_per_ton_cents`, the avoided landfill tipping fee per short ton that later drives cost-avoidance reporting, and `max_rebate_rate_per_ton_cents`, the site policy cap on contract rebate rates that guards the program's rebate exposure. A new site starts with a `certification_tier` of `NONE` and a `program_standing` of `GOOD_STANDING`. Both are computed attributes — the tier is derived from the site's certification history and the standing from its open contamination exposure — and they evolve with program events rather than through direct edits.

A `CertificationOfficer` registers each hauler, recycler, or processor by `name` and `vendor_type`, the latter drawn from `HAULER`, `RECYCLER`, and `PROCESSOR`; every vendor enters the registry `ACTIVE`. When a vendor's performance or paperwork lapses, the `CertificationOfficer` suspends it by setting `to_status` to `SUSPENDED`, which requires the vendor to currently be `ACTIVE` — any other starting state is rejected with `ERR_INVALID_STATE`. Suspension cascades down the chain: every `ACTIVE` contract of that vendor moves to `SUSPENDED`, and each newly suspended contract rejects its still-`PENDING` tickets, stamping `rejection_reason` as `CONTRACT_SUSPENDED` and shrinking the provisional totals of the periods that contained them. Setting `to_status` back to `ACTIVE` — permitted only from `SUSPENDED` — returns the vendor's `SUSPENDED` contracts to `ACTIVE`, but tickets rejected during the suspension stay `REJECTED`; there is no automatic reopen, and the vendor must correct and resubmit each one individually (see §3.3).

### 3.2. Vendor Contracts: Windows, Overlap, and the Fiscal Cap

A `SustainabilityManager` drafts a contract by naming the contracted facility (`site_id`), the contracted hauler or recycler (`vendor_id`), the covered `material_stream` — one of `MIXED_RECYCLABLES`, `CARDBOARD`, `COMPOST_ORGANICS`, `MIXED_SOLID_WASTE`, or `E_WASTE` — and the commercial terms: `rebate_per_ton_cents`, paid to the site per diverted short ton, and `contamination_penalty_per_ton_cents`, charged per ton when a ticket's contamination reaches the critical floor described in §3.7. The contract's `window_start` and `window_end` are ISO dates forming a closed interval, both endpoints inclusive, so `window_start` must be on or before `window_end`; an inverted window is rejected with `ERR_WINDOW_INVALID` (HTTP 422). A newly created contract begins in `DRAFT`.

Activation applies four gates, evaluated in order. First, the contract must be `DRAFT`; otherwise the request is rejected with `ERR_INVALID_STATE`. Second, no other `ACTIVE` contract for the same site and `material_stream` may have a window overlapping the candidate's closed interval — because both intervals are closed, two windows that merely touch at an endpoint do overlap, and the activation fails with `ERR_CONTRACT_STREAM_OVERLAP` (HTTP 409). Third, the contracted vendor must be `ACTIVE`; activating against a suspended vendor is rejected with `ERR_VENDOR_NOT_ACTIVE` (HTTP 409). Fourth, the fiscal guard: `rebate_per_ton_cents` must not exceed the site's `max_rebate_rate_per_ton_cents` policy cap, or activation is rejected with `ERR_REBATE_RATE_CAP_EXCEEDED` (HTTP 422).

Once active, a contract leaves `ACTIVE` in three ways. A `SustainabilityManager` may terminate it — permitted from either `ACTIVE` or `SUSPENDED` and rejected with `ERR_INVALID_STATE` from any other state — moving it to `TERMINATED` and rejecting every `PENDING` ticket riding on it with `rejection_reason` set to `CONTRACT_TERMINATED`, shrinking the containing periods' provisional totals. Vendor suspension moves a contract from `ACTIVE` to `SUSPENDED` as described in §3.1, and vendor reactivation moves it back from `SUSPENDED` to `ACTIVE`. Finally, the period-close sweep of §3.4 expires any contract of the closing site — whether `ACTIVE` or `SUSPENDED` — whose `window_end` is earlier than the logical clock date, moving it to `EXPIRED`. `TERMINATED` and `EXPIRED` are terminal states. Contracts may be listed with filters on `site_id`, `vendor_id`, `status`, and `material_stream`, or retrieved individually by `contract_id`.

### 3.3. Weight Tickets: Capture, Stewardship, and the Correction Loop

Recording a load is the `VendorUser`'s job — data stewards never create tickets. The payload carries the `site_id` of the facility that generated the load, the `vendor_id` of the hauler, the `contract_id` the load bills against, the load's `material_stream` drawn from the same five-stream enumeration as contracts, its `disposal_route` — `RECYCLING`, `COMPOSTING`, `REUSE`, `LANDFILL`, or `ENERGY_RECOVERY` — the scale readings `gross_weight_lbs` and `tare_weight_lbs`, the `ticket_date` of the haul, and the hauler's own `external_ticket_ref`. A `contamination_pct` may optionally accompany the ticket; when present it must lie between 0 and 100 inclusive, and when absent it is treated as 0 in rebate math.

Ownership is enforced before anything else about the payload: the body's `vendor_id` must equal the caller's `X-User-ID`, or the create is rejected with `ERR_VENDOR_MISMATCH`. The remaining create-time checks then run in the pipeline order of §2.8: payload well-formedness, including the contamination range (`ERR_INVALID_REQUEST`); existence of the referenced site, vendor, and contract (`ERR_NOT_FOUND`); uniqueness of the pair of `vendor_id` and `external_ticket_ref` across that vendor's non-`VOIDED` tickets (`ERR_DUPLICATE_TICKET_REF`, HTTP 409); both weights positive integers with the gross strictly greater than the tare (`ERR_INVALID_WEIGHTS`, HTTP 422); the ticket's `material_stream` equal to the referenced contract's `material_stream` (`ERR_STREAM_CONTRACT_MISMATCH`, HTTP 422); the contract `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`, HTTP 409); and the contract's own `site_id` and `vendor_id` matching the ticket body (`ERR_CROSS_SITE_REFERENCE`, HTTP 422).

A created ticket starts `PENDING`, with `net_weight_lbs` computed by the server as the gross weight minus the tare weight — any client-supplied value for it is ignored. When an `OPEN` scorecard period of the site contains the `ticket_date`, the new ticket joins that period's provisional set: the period's `total_waste_lbs_provisional` grows by the net weight, `diverted_lbs_provisional` grows as well when the route is a diverted route, and the period's `version` increments.

Validation by a `DataSteward` moves the ticket from `PENDING` to `VALIDATED` and applies five gates, evaluated in order: the ticket must be `PENDING` (`ERR_TICKET_NOT_PENDING`); its contract must be `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`); its vendor must be `ACTIVE` (`ERR_VENDOR_NOT_ACTIVE`); the `ticket_date` must not be later than the logical clock date (`ERR_TICKET_DATE_FUTURE`, HTTP 422); and an `OPEN` scorecard period of the site must contain the `ticket_date` within its half-open window (`ERR_NO_OPEN_PERIOD`, HTTP 409). On success, the containing period's certified totals accrue the ticket's `net_weight_lbs` — the diverted pounds as well when the route is diverted — the period's `rebate_estimate_cents` accrues the per-ticket estimate of §3.7, and the period's `version` increments. Provisional membership does not change at validation: the ticket was already counted while `PENDING`.

Rejection by a `DataSteward` requires only that the ticket be `PENDING`, failing otherwise with `ERR_TICKET_NOT_PENDING`; it records the supplied `reason` as the ticket's `rejection_reason`, drops the ticket out of the provisional set so the period's provisional totals shrink, and increments the period's `version`. The correction loop then belongs to the vendor: a `VendorUser` may resubmit a `REJECTED` ticket — only from `REJECTED`, otherwise `ERR_TICKET_NOT_REJECTED`, and only their own, with `X-User-ID` equal to the ticket's `vendor_id`, otherwise `ERR_VENDOR_MISMATCH` — optionally supplying corrected `gross_weight_lbs`, `tare_weight_lbs`, `ticket_date`, `contamination_pct`, or `disposal_route`. Resubmission applies the corrections, recomputes `net_weight_lbs`, clears `rejection_reason`, returns the ticket to `PENDING`, and grows the containing period's provisional totals and `version` once more.

Voiding is the compensating action for a validated load. A `DataSteward` may void a ticket, optionally attaching a `reason`, only from `VALIDATED` — otherwise `ERR_TICKET_NOT_VALIDATED`. The void subtracts exactly the ticket's `net_weight_lbs` from the period's certified totals, compensating the validation accrual exactly, reverses the ticket's accrued rebate estimate exactly, and increments the period's `version`. `VOIDED` is terminal, and because the duplicate-reference check ignores `VOIDED` tickets, a voided ticket's `external_ticket_ref` becomes available for reuse. The system itself can also void a validated ticket when a `CRITICAL` contamination event is linked to it (see §3.5). Tickets may be listed with filters on `site_id`, `vendor_id`, `contract_id`, or `validation_status`, and fetched individually by `ticket_id`.

### 3.4. Scorecard Periods and the Two Diversion Rates

A `CertificationOfficer` opens a scorecard period for a site by supplying `site_id`, `period_start`, and `period_end`. The window is half-open — `period_start` inclusive, `period_end` exclusive — and the start must be strictly earlier than the end, otherwise `ERR_WINDOW_INVALID`. Two guards then apply at creation, in this order: if the site already has an `OPEN` period the request is rejected with `ERR_PERIOD_ALREADY_OPEN` (HTTP 409); only if that guard passes does the overlap guard fire — no other period of the site, whatever its status, may overlap the half-open window, or the create fails with `ERR_PERIOD_OVERLAP` (HTTP 409). A new period starts `OPEN` with every computed total initialized to 0 and both `rebate_settled_cents` and `cost_avoided_cents` null; those two remain null for as long as the period stays open.

While a period is `OPEN`, its scorecard is live. The **certified** figures cover the site's `VALIDATED` tickets whose `ticket_date` falls in the window: `total_waste_lbs_validated` sums their `net_weight_lbs`, and `diverted_lbs_validated` sums the same measure over tickets whose `disposal_route` is one of the three diverted routes — `RECYCLING`, `COMPOSTING`, or `REUSE`; `LANDFILL` and `ENERGY_RECOVERY` never count as diverted. The `diversion_rate_certified_pct` is the diverted pounds multiplied by 100 and divided by the total pounds, rounded half-up to two decimal places, or exactly 0.00 when the total is zero. The **provisional** figures widen the set to include `PENDING` tickets alongside `VALIDATED` ones — `REJECTED` and `VOIDED` tickets are excluded from both sets — producing `total_waste_lbs_provisional`, `diverted_lbs_provisional`, and `diversion_rate_provisional_pct` by the same arithmetic. Because the provisional set includes still-unvalidated loads, identical ticket data yields a different provisional rate whenever any in-window ticket remains `PENDING`. The provisional variant exists for live monitoring while the period is open; the certified variant is the one that certification review, goal evaluation, and the closed scorecard rely on. Meanwhile the live `rebate_estimate_cents` aggregates the per-ticket estimates of §3.7 over the window's `VALIDATED` diverted tickets using ticket-reported contamination, and `contamination_event_count` counts the site's non-`DISMISSED` contamination events whose `event_date` falls in the window.

Closing a period is a `CertificationOfficer` action with two preconditions: the period must be `OPEN`, otherwise `ERR_INVALID_STATE`, and no `PENDING` ticket of the site may have a `ticket_date` inside the window, otherwise `ERR_PERIOD_HAS_PENDING_TICKETS` (HTTP 409). Closure is a sweep with several effects, applied together: the period moves to `CLOSED` and every computed figure — the certified and provisional totals, both diversion rates, the rebate estimate, and `contamination_event_count` — freezes; `rebate_settled_cents` is computed under the audit-adjusted settlement rule of §3.7 and frozen; `cost_avoided_cents` is computed with per-ticket rounding and frozen; every `ACTIVE` site goal whose window is fully contained in the period window is evaluated to `ACHIEVED` or `MISSED` per §3.6; every contract of the site whose `window_end` is earlier than the logical clock date moves to `EXPIRED`, whether it was `ACTIVE` or `SUSPENDED`; and every `APPROVED` certification application of the site whose `decided_at` plus twelve calendar months is strictly earlier than the logical clock date moves to `LAPSED`, with the site's `certification_tier` re-derived per §3.8. `CLOSED` is terminal. Periods may be listed with filters on `site_id` and `status`, or read individually by `period_id`; while a period is `OPEN`, reads return the live computed totals.

### 3.5. Audits, Contamination Events, and Corrective Training

Field verification begins with the `WasteAuditor`. A characterization audit records the audited `site_id`, the `audit_date`, the lead `auditor_name`, and `stream_findings` — an array of per-stream measurements, each entry carrying a `material_stream`, a `sampled_weight_lbs`, and a measured `contamination_pct`. Audits are immutable evidence: once recorded, an audit is never updated, carrying no `updated_at` or `version` per §2.4. Audits may be listed filtered by `site_id` or fetched by `audit_id`; their settlement-time role appears in §3.7.

When contamination is observed — on the tipping floor, on a specific load, or during an audit — the `WasteAuditor` records an event with the `site_id`, the `event_date`, the affected `material_stream`, and the measured `contamination_pct` between 0 and 100, optionally tying it to the offending load via `ticket_id` or to the source audit via `audit_id`. A linked ticket must belong to the event's site, otherwise `ERR_CROSS_SITE_REFERENCE`. The event's `severity` is computed from the percentage with floors inclusive at the boundary: below 5 the event is `MINOR`; at least 5 but below 10 it is `MAJOR`, so exactly 5.0 is `MAJOR`; at least 10 it is `CRITICAL`, so exactly 10.0 is `CRITICAL`. New events open in `OPEN` status.

A `CRITICAL` event has immediate teeth. If it is linked to a `VALIDATED` ticket, that ticket is voided on the spot — the `VALIDATED` → `VOIDED` transition runs with its full compensation of certified totals and rebate estimate — while a linked `PENDING` ticket is rejected instead.

The corrective-training lifecycle then runs. Assigning training — permitted only from `OPEN`, otherwise `ERR_INVALID_STATE` — records `trainee_name` and `training_due_date` and moves the event to `TRAINING_ASSIGNED`. Completing training moves it from `TRAINING_ASSIGNED` to `TRAINING_COMPLETED`. Verification takes a `passed` flag and is permitted only from `TRAINING_COMPLETED`: when `passed` is true the event moves to `VERIFIED_CLOSED`, a terminal state; when `passed` is false the event loops back to `OPEN` with `trainee_name` and `training_due_date` cleared, and the cycle restarts. A `WasteAuditor` may instead dismiss an `OPEN` event as erroneous, recording the supplied `reason` as `dismiss_reason`; `DISMISSED` is the other terminal state. Every wrong-status action on this lifecycle is rejected with `ERR_INVALID_STATE`.

Each of these mutations re-derives the site's `program_standing` — including dismissal, which excludes the event from further consideration. Standing is computed over the site's non-terminal events, meaning those in `OPEN`, `TRAINING_ASSIGNED`, or `TRAINING_COMPLETED`; `DISMISSED` and `VERIFIED_CLOSED` events are excluded from the derivation, and dismissed events also drop out of every period's `contamination_event_count`. If any non-terminal event is `CRITICAL`, the site is on `PROBATION`. Otherwise, if at least two non-terminal events exist, the site is on `WATCH`. Otherwise the site is in `GOOD_STANDING`. Standing, in turn, gates certification submission in §3.8. Events may be listed with filters on `site_id`, `ticket_id`, `audit_id`, or `status`, and fetched individually by `event_id`.

### 3.6. Site Goals and Their Evaluation at Close

A `SustainabilityManager` sets a site goal with the owning `site_id`, a `metric` — `DIVERSION_RATE`, `COST_AVOIDANCE`, or `CONTAMINATION_EVENTS` — a `target_value`, and a half-open window running from `window_start` inclusive to `window_end` exclusive; the start must be strictly earlier than the end, otherwise `ERR_WINDOW_INVALID`. The target's unit follows the metric: a percentage for `DIVERSION_RATE`, integer cents for `COST_AVOIDANCE`, and a maximum event count for `CONTAMINATION_EVENTS`. Two `ACTIVE` goals of the same site and metric may not have overlapping windows, rejected with `ERR_GOAL_WINDOW_OVERLAP` (HTTP 409) — but because goal windows are half-open, adjacency is allowed, so one goal's `window_end` may equal another's `window_start`. New goals start `ACTIVE`, and a `SustainabilityManager` may cancel an `ACTIVE` goal, moving it to `CANCELLED`; cancelling from any other state is rejected with `ERR_INVALID_STATE`. Goals may be listed with filters on `site_id`, `metric`, or `status`, and fetched by `goal_id`.

Goals are judged only at period close, and only against certified figures. When a period closes, every `ACTIVE` goal of the site whose window is fully contained in the period's window — the goal's `window_start` on or after `period_start` and its `window_end` on or before `period_end` — is evaluated. A `DIVERSION_RATE` goal is achieved when the frozen `diversion_rate_certified_pct` is greater than or equal to the goal's `target_value`. A `COST_AVOIDANCE` goal is achieved when the frozen `cost_avoided_cents` is greater than or equal to its `target_value`. A `CONTAMINATION_EVENTS` goal is achieved when the frozen `contamination_event_count` is less than or equal to its `target_value`. Achieved goals move to `ACHIEVED` and the rest to `MISSED`; both are terminal. A goal whose window is not fully contained in the closing period simply stays `ACTIVE`, awaiting a period that covers it.

### 3.7. Rebate Estimates, Settlement, and Cost Avoidance

Three monetary computations ride on the ticket stream. All work in integer cents with round-half-up rounding, and all tonnage conversions use exactly 2,000 pounds per short ton.

The **per-ticket rebate estimate** accrues when a ticket is validated, and only for diverted-route tickets — `RECYCLING`, `COMPOSTING`, or `REUSE`. `LANDFILL` and `ENERGY_RECOVERY` loads accrue zero: no rebate, no penalty. For a diverted ticket on its contract, the tonnage is the ticket's `net_weight_lbs` divided by 2,000 as an exact decimal with no intermediate rounding, and the contamination percentage is the ticket's own `contamination_pct`, treated as 0 when absent. A quality factor scales the rebate: 1.0 when the percentage is below 5; 0.75 when it is at least 5 but below 10; 0.5 when it is at least 10. The rebate part is the tonnage multiplied by the contract's `rebate_per_ton_cents` multiplied by the quality factor, rounded half-up to whole cents. The penalty part applies only when the percentage is at least 10: the tonnage multiplied by the contract's `contamination_penalty_per_ton_cents`, likewise rounded half-up to whole cents; otherwise the penalty part is zero. The ticket's estimate is the rebate part minus the penalty part, and it accrues into the containing period's `rebate_estimate_cents`. Voiding the ticket later reverses its accrued estimate exactly.

The **audit-adjusted settlement** runs at period close and produces the frozen `rebate_settled_cents`. It recomputes the same per-ticket arithmetic over the window's `VALIDATED` diverted tickets with one substitution: for each material stream, if a waste audit of the same site has an `audit_date` inside the period window and reports that stream in its `stream_findings`, the audit's `contamination_pct` replaces every such ticket's own percentage for that stream. When several audits of the site cover the same stream inside the window, the one with the greatest `audit_date` wins, with ties broken by the greatest `created_at`; tickets in streams that no covering audit measured keep their own `contamination_pct`. The settlement is the sum of those recomputed per-ticket amounts.

**Cost avoidance**, also computed at close and frozen into `cost_avoided_cents`, values each `VALIDATED` diverted-route ticket in the window at the landfill fee it avoided: the ticket's `net_weight_lbs` divided by 2,000, multiplied by the site's `landfill_tip_fee_per_ton_cents`, rounded half-up to whole cents per ticket. The rounding order is pinned: each ticket is rounded to cents first, and the period total is the sum of those rounded per-ticket amounts. Summing tonnage first and rounding once at the end produces a different total and is not the specified behavior.

### 3.8. Certification Applications: Drafting, Review, and Life After Approval

A `SustainabilityManager` drafts an application with the applicant `site_id`, the `level_requested` — `BRONZE`, `SILVER`, `GOLD`, or `ZERO_WASTE` — the `reporting_period_id` of the closed scorecard period whose certified metrics justify the request, and the concurrency field `expected_site_version` described in §2.7. The reporting period must belong to the same site, otherwise `ERR_CROSS_SITE_REFERENCE`. Creating the draft carries a superseding side effect: any existing `DRAFT` application of the same site for the same level moves to `WITHDRAWN`, and the site's `version` increments by one — which is precisely why the stale-version guard exists.

Submission moves the application from `DRAFT` to `SUBMITTED` through four gates, evaluated in order: the application must be `DRAFT` (`ERR_APPLICATION_NOT_DRAFT`); the site's `program_standing` must not be `PROBATION` (`ERR_STANDING_PROBATION`, HTTP 409); the reporting period must belong to the same site (`ERR_CROSS_SITE_REFERENCE`); and that period must be `CLOSED` (`ERR_PERIOD_NOT_CLOSED`, HTTP 409). A successful submission records the caller's `X-User-ID` as `submitted_by`. A `CertificationOfficer` then takes the application from `SUBMITTED` to `UNDER_REVIEW`; attempted from any other state, this step is rejected with `ERR_APPLICATION_NOT_SUBMITTED`.

Decision is the `CertificationOfficer`'s call, made with an `outcome` of `APPROVED` or `REJECTED` and an optional `notes`. Three checks apply, in order. The application must be `UNDER_REVIEW`, otherwise `ERR_APPLICATION_NOT_IN_REVIEW`. Segregation of duties requires the decider's `X-User-ID` to differ from the recorded `submitted_by` — the person who submitted an application may not decide it — and a self-decision is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). On an approving outcome only, the reporting period's frozen `diversion_rate_certified_pct` must meet the requested level's threshold — 50.0 for `BRONZE`, 70.0 for `SILVER`, 85.0 for `GOLD`, and 90.0 for `ZERO_WASTE` — compared with the boundary inclusive and with no further rounding at decision time, so exactly 90.00 earns `ZERO_WASTE`; a shortfall is rejected with `ERR_CERTIFICATION_THRESHOLD_NOT_MET` (HTTP 422). Either outcome records the decider's `X-User-ID` as `decided_by` and the logical clock timestamp as `decided_at`.

Approval ripples outward. Any prior `APPROVED` application of the same site moves to `SUPERSEDED`, and the site's `certification_tier` becomes the newly approved application's `level_requested`. Rejection is not the end of the road: a `SustainabilityManager` may revise a rejected application, returning it from `REJECTED` to `DRAFT` with `submitted_by`, `decided_by`, and `decided_at` cleared for another attempt; revision from any other state is rejected with `ERR_APPLICATION_NOT_DRAFT`. Approvals also age out on their own: when the close sweep of §3.4 finds an `APPROVED` application whose `decided_at` plus twelve calendar months is strictly earlier than the logical clock date, the application moves to `LAPSED`. After any of these events the site's `certification_tier` is re-derived as the level of its `APPROVED`, non-`LAPSED`, non-`SUPERSEDED` application with the greatest `decided_at`, falling back to `NONE` when no such application remains. `WITHDRAWN`, `SUPERSEDED`, and `LAPSED` are terminal. Applications may be listed with filters on `site_id`, `reporting_period_id`, or `status`, and fetched by `application_id`.

## 4. Endpoint Definitions

The table below summarizes every endpoint. Operations that create a new resource respond with 201 Created; reads and operations that modify an existing resource — state transitions, corrections, decisions, sweeps — respond with 200 OK. Request and response bodies follow the envelope of §2.2, validation follows the pipeline of §2.8, and the preconditions, parameters, and side effects behind each row are governed by the narratives of §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /sites | Create a site enrolled in the program | SustainabilityManager |
| GET | /sites/{site_id} | Get a site | SustainabilityManager, VendorUser, DataSteward, WasteAuditor, CertificationOfficer |
| POST | /vendors | Register a hauler/recycler vendor | CertificationOfficer |
| GET | /vendors/{vendor_id} | Get a vendor | SustainabilityManager, VendorUser, DataSteward, WasteAuditor, CertificationOfficer |
| POST | /vendors/{vendor_id}/set_status | Suspend or reactivate a vendor; suspension cascades to contracts and their PENDING tickets | CertificationOfficer |
| POST | /contracts | Create a vendor contract in DRAFT | SustainabilityManager |
| GET | /contracts/{contract_id} | Get a contract | SustainabilityManager, VendorUser, DataSteward, WasteAuditor, CertificationOfficer |
| GET | /contracts | List contracts with filters | SustainabilityManager, VendorUser, DataSteward, WasteAuditor, CertificationOfficer |
| POST | /contracts/{contract_id}/activate | Activate a DRAFT contract (overlap, vendor, and fiscal-cap checks) | SustainabilityManager |
| POST | /contracts/{contract_id}/terminate | Terminate an ACTIVE or SUSPENDED contract; its PENDING tickets are rejected | SustainabilityManager |
| POST | /tickets | Record a hauler weight ticket (VendorUser may only create for own vendor_id) | VendorUser |
| GET | /tickets/{ticket_id} | Get a ticket | SustainabilityManager, VendorUser, DataSteward, WasteAuditor, CertificationOfficer |
| GET | /tickets | List tickets with filters | SustainabilityManager, VendorUser, DataSteward, WasteAuditor, CertificationOfficer |
| POST | /tickets/{ticket_id}/validate | Validate a PENDING ticket | DataSteward |
| POST | /tickets/{ticket_id}/reject | Reject a PENDING ticket | DataSteward |
| POST | /tickets/{ticket_id}/resubmit | Vendor corrects a REJECTED ticket back to PENDING | VendorUser |
| POST | /tickets/{ticket_id}/void | Void a VALIDATED ticket (compensates totals and rebate accrual) | DataSteward |
| POST | /audits | Record a waste characterization audit (immutable once created) | WasteAuditor |
| GET | /audits/{audit_id} | Get an audit | SustainabilityManager, VendorUser, DataSteward, WasteAuditor, CertificationOfficer |
| GET | /audits | List audits with filters | SustainabilityManager, VendorUser, DataSteward, WasteAuditor, CertificationOfficer |
| POST | /contamination_events | Record a contamination observation; a CRITICAL event linked to a VALIDATED ticket voids that ticket (a PENDING one is rejected) | WasteAuditor |
| GET | /contamination_events/{event_id} | Get a contamination event | SustainabilityManager, VendorUser, DataSteward, WasteAuditor, CertificationOfficer |
| GET | /contamination_events | List contamination events with filters | SustainabilityManager, VendorUser, DataSteward, WasteAuditor, CertificationOfficer |
| POST | /contamination_events/{event_id}/assign_training | Assign corrective training for an OPEN event | WasteAuditor |
| POST | /contamination_events/{event_id}/complete_training | Mark assigned training completed | WasteAuditor |
| POST | /contamination_events/{event_id}/verify | Verify corrective action; passed=false loops the event back to OPEN | WasteAuditor |
| POST | /contamination_events/{event_id}/dismiss | Dismiss an OPEN event as erroneous | WasteAuditor |
| POST | /goals | Create a site goal (half-open window; adjacency with existing goals allowed) | SustainabilityManager |
| GET | /goals/{goal_id} | Get a goal | SustainabilityManager, VendorUser, DataSteward, WasteAuditor, CertificationOfficer |
| GET | /goals | List goals with filters | SustainabilityManager, VendorUser, DataSteward, WasteAuditor, CertificationOfficer |
| POST | /goals/{goal_id}/cancel | Cancel an ACTIVE goal | SustainabilityManager |
| POST | /scorecard_periods | Open a new scorecard period (non-overlapping; at most one OPEN per site) | CertificationOfficer |
| GET | /scorecard_periods/{period_id} | Get a scorecard period (live computed totals while OPEN) | SustainabilityManager, VendorUser, DataSteward, WasteAuditor, CertificationOfficer |
| GET | /scorecard_periods | List scorecard periods with filters | SustainabilityManager, VendorUser, DataSteward, WasteAuditor, CertificationOfficer |
| POST | /scorecard_periods/{period_id}/close | Close the period: freeze totals, settle rebates, compute cost avoidance, evaluate contained goals, sweep contract expiry and certification lapse | CertificationOfficer |
| POST | /certification_applications | Create a draft application (OCC on Site.version; supersedes an existing DRAFT of the same site+level to WITHDRAWN) | SustainabilityManager |
| GET | /certification_applications/{application_id} | Get an application | SustainabilityManager, VendorUser, DataSteward, WasteAuditor, CertificationOfficer |
| GET | /certification_applications | List applications with filters | SustainabilityManager, VendorUser, DataSteward, WasteAuditor, CertificationOfficer |
| POST | /certification_applications/{application_id}/submit | Submit a DRAFT application (requires CLOSED reporting period and non-PROBATION standing) | SustainabilityManager |
| POST | /certification_applications/{application_id}/start_review | Move a SUBMITTED application to UNDER_REVIEW | CertificationOfficer |
| POST | /certification_applications/{application_id}/decide | Approve or reject an UNDER_REVIEW application (segregation of duties; threshold check on approve) | CertificationOfficer |
| POST | /certification_applications/{application_id}/revise | Return a REJECTED application to DRAFT for revision and resubmission | SustainabilityManager |
| POST | /_clock/set_current_utc | Set the logical clock (test-driving endpoint; default before any call is exactly 2026-08-01T00:00:00Z, and the logical clock never falls back to wall-clock time) | CertificationOfficer |

## 5. Error Code Catalogue

The table below enumerates every error identifier and its HTTP status. The conditions under which each error is raised are defined by the narratives of §2 and §3.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_VENDOR_MISMATCH | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_TICKET_NOT_PENDING | 409 |
| ERR_TICKET_NOT_REJECTED | 409 |
| ERR_TICKET_NOT_VALIDATED | 409 |
| ERR_DUPLICATE_TICKET_REF | 409 |
| ERR_INVALID_WEIGHTS | 422 |
| ERR_STREAM_CONTRACT_MISMATCH | 422 |
| ERR_CONTRACT_NOT_ACTIVE | 409 |
| ERR_CONTRACT_STREAM_OVERLAP | 409 |
| ERR_REBATE_RATE_CAP_EXCEEDED | 422 |
| ERR_VENDOR_NOT_ACTIVE | 409 |
| ERR_GOAL_WINDOW_OVERLAP | 409 |
| ERR_WINDOW_INVALID | 422 |
| ERR_PERIOD_OVERLAP | 409 |
| ERR_PERIOD_ALREADY_OPEN | 409 |
| ERR_PERIOD_HAS_PENDING_TICKETS | 409 |
| ERR_TICKET_DATE_FUTURE | 422 |
| ERR_NO_OPEN_PERIOD | 409 |
| ERR_CROSS_SITE_REFERENCE | 422 |
| ERR_APPLICATION_NOT_DRAFT | 409 |
| ERR_APPLICATION_NOT_SUBMITTED | 409 |
| ERR_APPLICATION_NOT_IN_REVIEW | 409 |
| ERR_PERIOD_NOT_CLOSED | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_STANDING_PROBATION | 409 |
| ERR_CERTIFICATION_THRESHOLD_NOT_MET | 422 |

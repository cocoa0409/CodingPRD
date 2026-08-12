# Utility Mutual Aid API — Product Requirements Document

## 1. Introduction

Mutual assistance is the electric utility industry's standing pact for emergencies. When a hurricane, wildfire, ice storm, or flood overwhelms a utility's own workforce, neighboring companies dispatch line crews, tree-trimming crews, damage assessors, substation specialists, and support personnel across service territories to help restore power. The host utility directs the work; the responding utilities carry the cost of wages, travel, lodging, and meals up front; and weeks later a painstaking reconciliation of timesheets, per-diem claims, mobilization fees, and invoices settles the accounts between companies. This document specifies the Utility Mutual Aid API, the system of record for one such program modeled on the EEI mutual assistance framework, covering the full arc from the first request for assistance through resource typing, crew roster and equipment commitment, travel and lodging logistics, safety briefings under host-utility rules, cross-company timekeeping, release and demobilization, invoice reconciliation and dispute, and the closing after-action report.

Two properties of the domain shape the entire design. First, money and safety both cross company boundaries, so the platform enforces strict segregation of duties — the operator who submits a timesheet may never certify it, the officer who conducts a safety briefing may never acknowledge it, and the finance operator who approves an invoice may never have certified any timesheet it covers. Second, field data and billing data legitimately diverge: a provisional invoice estimate and its final submitted figure can differ on identical raw rows, and an event's as-certified cost and as-billed cost are two distinct, equally valid views. The API therefore pins its billing basis explicitly — every certified timesheet carries the exact rate schedule that priced it — and it treats schedule supersession, safety holds, and demobilization as first-class cascades rather than informal conventions.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, conventions, and boilerplate that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which they act. A request in which either header is missing or malformed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The program recognizes exactly seven roles, spelled as follows: `ProgramAdmin`, `HostCoordinator`, `RespondingCoordinator`, `CrewSupervisor`, `HostSafetyOfficer`, `HostFinance`, and `RespondingFinance`. Each endpoint admits a fixed set of roles; a caller whose role is not admitted is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it to a resource's `id`. When `X-User-Role` is `HostCoordinator`, `RespondingCoordinator`, `HostSafetyOfficer`, `HostFinance`, or `RespondingFinance`, `X-User-ID` is the `id` of the acting `UtilityCompany`, and ownership checks compare that value to the foreign-key field that scopes the target resource — the event's `host_utility_id` for host-side actions, or the request's `responding_utility_id` / crew's `owning_utility_id` for responding-side actions. When `X-User-Role` is `CrewSupervisor`, `X-User-ID` is the `id` of the acting `Crew`, so a supervisor's authority extends only to that crew's timesheets and briefing acknowledgments. Any mismatch between an entity-backed caller's `X-User-ID` and the resource's owning scope is rejected with `ERR_SCOPE_MISMATCH` (HTTP 403).

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

List endpoints paginate through two query parameters. `limit` sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, and the `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

List endpoints also accept optional equality filters drawn from the resource's own fields: events filter by `host_utility_id` and `status`; rate schedules by `event_id`, `responding_utility_id`, `supersedes_schedule_id`, and `status`; assistance requests by `event_id`, `responding_utility_id`, and `status`; crews by `request_id`, `owning_utility_id`, `mobility_status`, and `readiness_status`; briefings by `crew_id`, `event_id`, and `status`; timesheets by `crew_id`, `status`, `certified_schedule_id`, and `billed_invoice_id`; lodging blocks by `event_id`; lodging assignments by `block_id`, `crew_id`, and `status`; per-diem claims by `crew_id` and `status`; invoices by `request_id`, `rate_schedule_id`, and `status`; and after-action reports by `event_id` and `status`.

### 2.4. The Program Logical Clock

All timestamped program events — an arrival, a release, a publication, a demobilization anchor — read a single program-wide logical clock rather than wall-clock time. Before any operator touches it, the clock stands at exactly `2026-05-01T00:00:00Z`, and it never falls back to wall-clock time thereafter. A `ProgramAdmin`-only test-driving capability sets the clock to a supplied instant passed as `to_iso8601` and returns the resulting `current_utc`; advancing the clock mutates nothing else in the system. Every rule in this document that speaks of "the current time", "the current date", or a deadline is evaluated against this logical clock.

### 2.5. Common Resource Properties

Every resource in the API — utility companies, events, rate schedules, assistance requests, crews, safety briefings, timesheets, lodging blocks, lodging assignments, per-diem claims, invoices, and after-action reports — carries four system-managed properties:

- `id` (string): a server-minted UUID with no type prefix, assigned at creation.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource, including mutations caused by another resource's cascade.

### 2.6. Money, Precision, and Rounding Discipline

All monetary values are integer cents; no fractional-cent value ever appears in a stored field or an API payload. Rate multipliers and premiums are expressed in basis points, where ten thousand basis points equal one hundred percent — a schedule's default `ot_multiplier_bps` of 15000 therefore means time-and-a-half, its default `dt_multiplier_bps` of 20000 means double time, and a `storm_premium_bps` of 1000 means a ten percent premium.

Rounding follows one discipline everywhere: each priced component is rounded half-up to whole cents at the exact point the relevant workflow names, and components already rounded are never re-rounded downstream. Per-diem claims in particular are priced per claim-day and rounded before any summation; summing unrounded daily values and rounding the total once is forbidden, because the two orders can differ by cents. Invoice-level totals are sums of already-rounded integer amounts, so no further rounding occurs at the invoice level.

### 2.7. Optimistic Concurrency Control on Schedule Publication

Exactly one operation in the API participates in optimistic concurrency control: publishing a billing-rate schedule that names a `supersedes_schedule_id`. Such a publication request must carry `expected_superseded_schedule_version` — a non-optional input whenever a supersession target is named — holding the `version` of the superseded schedule as the client last observed it. If the predecessor's current `version` no longer equals the presented value, the publication is rejected with `ERR_STALE_SCHEDULE_VERSION` (HTTP 412) and nothing is mutated; this protects a coordinator from superseding a predecessor whose state they have not observed, for instance when a different successor has already been published against the same predecessor and advanced its `version`. A publication that names no `supersedes_schedule_id` takes no version field at all, and no other endpoint in the API accepts or requires a version field — every other write is processed without an OCC check.

### 2.8. Event Intake Posture

Every event exposes a derived `intake_posture` that governs whether new assistance requests may be created against it. The posture is `SEALED` while the event's `status` is `DEMOBILIZING` or `CLOSED`; otherwise it is `RESTRICTED` once the event's `open_request_count` reaches three or more — exactly three open requests is enough to flip the posture — and otherwise it is `ACCEPTING`. The `open_request_count` itself counts the event's assistance requests whose `status` is `SUBMITTED` or `COUNTERED`. Both `RESTRICTED` and `SEALED` block the creation of new assistance requests with `ERR_EVENT_NOT_ACCEPTING_REQUESTS` (HTTP 409); only an `ACCEPTING` event admits them. The posture and the underlying count are recomputed immediately whenever the open-request population changes — on request submission, acceptance, decline, or cancellation — and on event lifecycle transitions such as activation and the start of demobilization.

### 2.9. Validation Order and Error Precedence

Every request is validated against a fixed, ordered sequence of rule families, and a failure surfaces the error of the earliest family that rejects it:

1. **Header presence** — `X-User-ID` and `X-User-Role` present and well-formed, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Applies to all endpoints.
2. **Role admission** — the caller's role is admitted by the endpoint, else `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403). Applies to all endpoints.
3. **Ownership scope** — an entity-backed caller's `X-User-ID` matches the resource's owning scope (the host utility for host actions, the responding or owning utility for responding actions, the crew itself for `CrewSupervisor`), else `ERR_SCOPE_MISMATCH` (HTTP 403). Applies to all mutating endpoints.
4. **Existence** — every referenced identifier exists, validated left-to-right with path parameters first and body-referenced identifiers after, else `ERR_NOT_FOUND` (HTTP 404) naming the first missing reference. Applies to all endpoints.
5. **State legality** — the target resource's current state permits the requested transition, including event and request postures that act as preconditions, else `ERR_INVALID_STATE_TRANSITION` (HTTP 409). Applies to all action endpoints.
6. **Safety gating** — crew readiness must be `CLEARED_TO_WORK` for timesheet certification and recertification, else `ERR_CREW_NOT_CLEARED` (HTTP 409). Safety outranks the temporal family: when a crew is on hold and the certification window has also closed, the rejection is `ERR_CREW_NOT_CLEARED`, never the window error.
7. **Temporal windows** — deadlines measured against the logical clock: the mobilization deadline on arrival confirmation (`ERR_MOBILIZATION_DEADLINE_PASSED`), the fourteen-day certification window on timesheet certification and recertification (`ERR_CERTIFICATION_WINDOW_CLOSED`), and the thirty-day invoice submission window on invoice submission (`ERR_INVOICE_WINDOW_CLOSED`), each HTTP 409.
8. **Referential consistency** — cross-references must be mutually consistent: a lodging block belongs to the crew's event, a briefing's event matches the crew's event, an invoice's pinned schedule belongs to the request's event and responding utility, else `ERR_REFERENTIAL_INTEGRITY` (HTTP 409).
9. **Constraint family** — uniqueness, capacity, overlap, posture, selector, supersession, segregation-of-duties, and the OCC stale-version check: `ERR_EVENT_NOT_ACCEPTING_REQUESTS`, `ERR_SCHEDULE_WINDOW_OVERLAP`, `ERR_SCHEDULE_NOT_PUBLISHED`, `ERR_NO_EFFECTIVE_SCHEDULE`, `ERR_SUPERSEDED_SCHEDULE`, `ERR_LODGING_CAPACITY_EXCEEDED`, `ERR_LODGING_OVERLAP`, `ERR_DUPLICATE_TIMESHEET`, `ERR_DUPLICATE_CLAIM`, `ERR_INVOICE_EXISTS`, `ERR_AAR_EXISTS`, and `ERR_SEGREGATION_OF_DUTIES` (all HTTP 409), plus `ERR_STALE_SCHEDULE_VERSION` at HTTP 412.
10. **Fiscal sanity** — amounts must be positive where required, payment must equal the outstanding balance exactly, disputes and credits must stay within their bounds, and a submitted invoice must be non-empty: `ERR_INVALID_AMOUNT` (HTTP 400), and `ERR_PAYMENT_AMOUNT_MISMATCH`, `ERR_DISPUTE_AMOUNT_INVALID`, `ERR_CREDIT_EXCEEDS_DISPUTED`, `ERR_EMPTY_INVOICE` (HTTP 409). This family guards invoice payment, dispute, credit proposal, arbitration, and submission.

### 2.10. Cascading Side Effects and Ledger Synchronization

State changes in this domain rarely stay on one row. An arrival ripples into lodging and request-level deployability; a safety suspension ripples into timesheets, per-diem claims, and the request's fulfillment standing; a crew release checks rooms out of their hotel block. The server performs these cascades immediately, as part of the same write that triggered them, recomputing every derived counter and ledger total the moment its inputs change rather than deferring reconciliation. Each mutation — including a mutation one resource causes on another — refreshes the affected resource's `updated_at` and increments its `version`.

Two compensating invariants keep the ledgers honest across reversal paths. Committing a crew and later withdrawing it leaves the request's `committed_crew_count` exactly where it started, because a crew in `WITHDRAWN` no longer counts. Likewise, submitting an invoice and later voiding it leaves the event's `total_invoiced_cents` and the request's `invoiced_total_cents` exactly where they stood before the submission, because a `VOID` invoice no longer contributes to either total.

## 3. Business Logic & Workflows

### 3.1. Enrolling Utilities and Declaring Events

Before any storm work can be coordinated, a `ProgramAdmin` enrolls each participating company by providing its legal `name`, a program-wide `company_code` such as `HELCO`, its `role_capability` — one of `HOST`, `RESPONDING`, or `BOTH`, declaring which side(s) of mutual aid the company may act on — and a free-form `home_region`. Company codes are unique across all registered companies; a duplicate `company_code` is rejected with `ERR_INVALID_REQUEST`.

When an emergency materializes, a `ProgramAdmin` declares the event with an `event_name` (say, "Hurricane Idalia"), the `host_utility_id` of the utility requesting aid, an `event_type` of `STORM`, `WILDFIRE`, `ICE`, or `FLOOD`, and the `declared_start_date` of the event period. Two further date fields define the storm-premium window: work performed on or after `premium_window_start` and on or before `premium_window_end` — both bounds inclusive — earns the schedule's storm premium. The `mobilization_deadline` sets the latest instant by which committed crews must have arrived. A new event opens in `OPEN` status with an `ACCEPTING` intake posture, and activation by a `ProgramAdmin` moves it from `OPEN` to `ACTIVE`, leaving the posture to be recomputed from the open-request population.

Demobilization begins when the host utility's `HostCoordinator` — whose `X-User-ID` must equal the event's `host_utility_id`, on pain of `ERR_SCOPE_MISMATCH` — triggers the transition from `ACTIVE` to `DEMOBILIZING`. That single write stamps `demobilized_at` with the current logical clock (the anchor for the thirty-day invoice submission window described in §3.8), flips `intake_posture` to `SEALED` so no new requests can be created, and increments the event's `version`. The final transition from `DEMOBILIZING` to `CLOSED` belongs to a `ProgramAdmin` and is gated by the closeout conditions of §3.9.

### 3.2. Rate Schedules: Drafting, Publication, and Supersession

Each responding utility prices its own participation. A `RespondingCoordinator` drafts a billing-rate schedule for a chosen `event_id`; the server stamps the schedule's `responding_utility_id` from the caller's `X-User-ID`, tying the rate card to that coordinator's company. The coverage window runs from `effective_start_date` through `effective_end_date`, both bounds inclusive — a closed interval. The draft carries `rate_lines`, one entry per crew type pairing a `crew_type` with its `hourly_rate_cents`; a `storm_premium_bps`; the `per_diem_rate_cents` for member meals and incidentals; the `per_diem_method`, either `STANDARD` or `ACTUAL`, which selects the claim-pricing variant of §3.6; and `mobilization_fee_tiers`, an ascending ladder of brackets each pairing a `min_subtotal_cents` threshold with a `fee_bps` rate; the server does not validate the ladder's shape at draft time, and if no bracket's threshold is at most the subtotal the mobilization fee is zero. Overtime mechanics default sensibly and may be overridden: `ot_multiplier_bps` defaults to 15000 (time-and-a-half), `dt_multiplier_bps` to 20000 (double time), `ot_threshold_minutes` to 480 — the first eight hours of a work day bill at straight time — and `dt_threshold_minutes` to 960, sixteen hours, beyond which double time applies. An optional `supersedes_schedule_id` names a predecessor schedule this one replaces. New schedules are born `DRAFT` with no `published_at`.

Publication moves a schedule from `DRAFT` to `PUBLISHED` and enforces three checks in order. First, the event must be `OPEN` or `ACTIVE`; attempting to publish against a demobilizing or closed event is rejected with `ERR_INVALID_STATE_TRANSITION` — the invoice-oriented `ERR_EVENT_NOT_DEMOBILIZING` is never used at publication. Second, a closed-interval overlap check: no other schedule for the same event and responding utility in `PUBLISHED` or `LOCKED` status may have a coverage window intersecting this one, and because both ends are inclusive an existing window ending 2026-05-31 conflicts with a new window starting 2026-05-31; a violation is rejected with `ERR_SCHEDULE_WINDOW_OVERLAP`, and the schedule named by `supersedes_schedule_id` is exempt from this check. Third, when a supersession target is named, the request must carry `expected_superseded_schedule_version` matching the predecessor's current `version`, failing which the publication is rejected with `ERR_STALE_SCHEDULE_VERSION` (HTTP 412) exactly as §2.7 specifies. A successful publication stamps `published_at` with the logical clock, and when a predecessor was named it moves that predecessor to `SUPERSEDED` regardless of the predecessor's prior status and increments the predecessor's `version` by one — the bump a stale reader will trip over at their own publication attempt.

The host utility's `HostFinance` may then lock a published schedule, moving it from `PUBLISHED` to `LOCKED`, once the billing basis is settled ahead of invoicing; the caller's `X-User-ID` must equal the schedule event's `host_utility_id`. Both `PUBLISHED` and `LOCKED` schedules are valid pricing bases, and the publication-time overlap ban guarantees that for any given date at most one such schedule covers it for a given event and responding utility. Throughout this document, "the effective schedule" for a crew and a date means that unique `PUBLISHED` or `LOCKED` schedule for the crew's event and owning utility whose inclusive coverage window contains the date.

### 3.3. Request Negotiation and Crew Commitment

A host utility asks for help by drafting an assistance request. The `HostCoordinator` supplies the `event_id`, the `responding_utility_id` the request is addressed to, the resource-typed `requested_crews` as a list of `crew_type` and `count` pairs, the `required_minimum_crews` that define fulfillment, and the deployment window `earliest_start_date` through `latest_end_date` — a start after the end is rejected with `ERR_INVALID_REQUEST`. Creation is permitted only while the event's `intake_posture` is `ACCEPTING`; against a `RESTRICTED` or `SEALED` event it fails with `ERR_EVENT_NOT_ACCEPTING_REQUESTS`. A new request is a `DRAFT` with `amendment_round` zero, empty `counter_terms`, and all derived counts at zero.

Negotiation proceeds as a cycle between the two coordinators. Submission by the host — scope-checked against the event's `host_utility_id` — moves `DRAFT` to `SUBMITTED` and immediately recomputes the event's `open_request_count`, which may flip the intake posture from `ACCEPTING` to `RESTRICTED` at the three-request threshold. The responding utility's `RespondingCoordinator`, scoped to the request's `responding_utility_id`, may counter, moving `SUBMITTED` to `COUNTERED` and recording the supplied `counter_crews` and optional `counter_note` into the request's `counter_terms`. The host answers a counter by resubmitting with amended terms: resubmission from `COUNTERED` requires `amended_crews` in the payload — its absence is an `ERR_INVALID_REQUEST` — and replaces `requested_crews` with the amendment, replaces `required_minimum_crews` when `amended_required_minimum` is present, and increments `amendment_round` by one. The `SUBMITTED` to `COUNTERED` to `SUBMITTED` cycle may repeat without bound, with `amendment_round` tracking the rounds.

Acceptance by the responding coordinator moves `SUBMITTED` to `ACCEPTED`, but only when a billing-rate schedule for this event and responding utility exists in `PUBLISHED` or `LOCKED` status; otherwise the acceptance is rejected with `ERR_SCHEDULE_NOT_PUBLISHED`. A request may also be declined by the responding coordinator from either `SUBMITTED` or `COUNTERED` — the server accepts the decline call without recording any accompanying payload field — or cancelled by the host coordinator from `DRAFT`, `SUBMITTED`, or `COUNTERED`. `DECLINED` and `CANCELLED` are terminal, and every acceptance, decline, and cancellation recomputes the event's open-request count, so an acceptance that drains the open population can relax a `RESTRICTED` posture back to `ACCEPTING`.

With an accepted request in hand, the responding coordinator commits crews. Crew creation carries the `request_id`, a `crew_type` of `LINE`, `TREE`, `DAMAGE_ASSESS`, `SUBSTATION`, or `SUPPORT`, a free-text `home_base`, a `roster` of `member_ref` and `member_role` pairs that must be non-empty — an empty roster is `ERR_INVALID_REQUEST` — and an `equipment_units` inventory of `unit_type`, `unit_ref`, and `daily_rate_cents` entries that may be empty. The server derives `roster_size` from the roster's length and `equipment_daily_total_cents` as the sum of the equipment daily rates, stamps `owning_utility_id` from the caller's `X-User-ID` (which must equal the request's `responding_utility_id`, enforced under the ownership-scope rule), and requires the request to be `ACCEPTED`, `IN_PROGRESS`, or `FULFILLED`. A crew is born with `mobility_status` `COMMITTED` and `readiness_status` `AWAITING_BRIEFING` — two independent status dimensions recorded on the same row, one tracking travel and demobilization, the other tracking safety clearance — and the request's `committed_crew_count` immediately reflects it. That count tallies the request's crews whose mobility is `COMMITTED`, `ARRIVED`, or `DEMOBILIZING`; the stricter `deployable_crew_count` tallies only crews that have both `ARRIVED` and `CLEARED_TO_WORK`, and it is this deployable count that fulfillment is measured against.

A committed crew that has not yet arrived can be pulled back: withdrawal by the owning utility's responding coordinator moves `mobility_status` from `COMMITTED` to `WITHDRAWN`, recomputes both crew counts, and — per the compensating invariant of §2.10 — a create-then-withdraw sequence leaves `committed_crew_count` exactly as it was before the commitment. If the request stood at `FULFILLED` and the withdrawal drops deployability below `required_minimum_crews`, the request is demoted back to `IN_PROGRESS`.

### 3.4. Mobilization: Arrival and Lodging

Lodging is arranged on the host side ahead of arrival. A `HostCoordinator` registers each hotel block with its `event_id`, `hotel_name`, the `block_code` confirmation, the `total_rooms` under block control, and the negotiated `nightly_rate_cents`; a fresh block's `assigned_rooms` is zero. Rooms are then allocated crew by crew: an assignment names the `block_id` and `crew_id`, the `room_count`, and a stay interval from `check_in_date` to `check_out_date` under half-open semantics — the crew occupies the check-in night through the night before check-out. Three guards protect the block, in the validation order of §2.9: the block must belong to the crew's event, else `ERR_REFERENTIAL_INTEGRITY`; the block must have room, meaning `assigned_rooms` plus the new `room_count` may not exceed `total_rooms` — equality is allowed, and any excess is `ERR_LODGING_CAPACITY_EXCEEDED`; and the same crew must not already hold a non-cancelled assignment whose half-open interval intersects the new one — a new stay whose `check_in_date` falls before an existing stay's `check_out_date` while the existing stay's `check_in_date` falls before the new `check_out_date` conflicts and is rejected with `ERR_LODGING_OVERLAP`, whereas back-to-back stays that merely touch at a boundary date are permitted. A new assignment is `RESERVED` and raises the block's `assigned_rooms` by its `room_count`; cancelling a `RESERVED` assignment (host scope) moves it to `CANCELLED` and frees those rooms again.

Arrival is confirmed by the host coordinator once a crew physically reports. The request must stand at `ACCEPTED`, `IN_PROGRESS`, or `FULFILLED` — confirming against any other request state is `ERR_INVALID_STATE_TRANSITION` — and the logical clock must not have passed the event's `mobilization_deadline`, else the confirmation is rejected with `ERR_MOBILIZATION_DEADLINE_PASSED`. A confirmed arrival stamps `arrived_at` and fires a three-link cascade: the crew's `RESERVED` lodging assignments move to `OCCUPIED` (still counted in `assigned_rooms`); the request's `deployable_crew_count` is recomputed, noting that deployability also depends on the crew's safety readiness; and the request itself advances — from `ACCEPTED` to `IN_PROGRESS` on its first arrival, and onward from `IN_PROGRESS` to `FULFILLED` the moment the deployable count reaches `required_minimum_crews`.

### 3.5. Safety Briefings, Suspension, and the Hold Cycle

No crew works until it has been briefed on host-utility rules and has acknowledged the briefing with a second pair of eyes. A `HostSafetyOfficer` scoped to the event's host utility conducts a briefing by supplying the `crew_id`, the `event_id` — which must equal the crew's event, else `ERR_REFERENTIAL_INTEGRITY` — their own `conductor_operator_ref`, the `host_rules_version` being acknowledged, and a non-empty list of `topics`, since an empty agenda is `ERR_INVALID_REQUEST`. A briefing is born already `CONDUCTED`, with `conducted_at` stamped from the logical clock. Its effect on the crew depends on where the crew stands in the readiness dimension: a crew `AWAITING_BRIEFING` moves to `BRIEFED`, and a crew under `SAFETY_HOLD` moves to `BRIEFED` only when the briefing's `conducted_at` is later than the crew's `last_suspended_at` — a briefing that predates the suspension cannot lift it.

Acknowledgment belongs to the `CrewSupervisor`, whose `X-User-ID` must equal the briefing's crew `id`. The acknowledging `supervisor_operator_ref` must differ from the `conductor_operator_ref` — the program forbids one operator from standing on both sides of the safety record, rejecting such an acknowledgment with `ERR_SEGREGATION_OF_DUTIES`. A clean acknowledgment records `acknowledged_at`, moves the briefing from `CONDUCTED` to `ACKNOWLEDGED`, and advances the crew from `BRIEFED` to `CLEARED_TO_WORK`. When the crew had been returning from a hold, the same acknowledgment fires the hold-release cascade: the crew's `HELD` timesheets and `HELD` per-diem claims return to `SUBMITTED`, the request's deployable count is recomputed, and a request that had been demoted to `IN_PROGRESS` climbs back to `FULFILLED` once the count again reaches `required_minimum_crews`.

Suspension runs the cascade in the opposite direction. When a `HostSafetyOfficer` suspends a crew the server accepts the call without recording any accompanying payload field — the crew's readiness drops from `CLEARED_TO_WORK` to `SAFETY_HOLD`, `last_suspended_at` is stamped, and a depth-three cascade follows. First the crew itself leaves the deployable population; second, every one of the crew's `SUBMITTED` timesheets and `SUBMITTED` per-diem claims is parked in `HELD`; third, the request's `deployable_crew_count` is recomputed and a `FULFILLED` request whose deployability has fallen below `required_minimum_crews` is demoted to `IN_PROGRESS`. The two status dimensions then evolve independently — a suspended crew may still travel, arrive, or be released — with one exception: release, described in §3.7, forces `readiness_status` to the terminal `RELEASED`, closing certification for that crew for good.

### 3.6. Timekeeping and Per-Diem: Capturing Field Costs

Field time is recorded one crew-day at a time. The `CrewSupervisor` drafts a timesheet with the `crew_id`, the `work_date`, a `day_classification` of `TRAVEL`, `WORK`, `STANDBY`, or `REST`, and optionally `reported_work_minutes` and `reported_travel_minutes`, both defaulting to zero. Only one timesheet may exist per crew and date; a second draft reusing the pair is rejected with `ERR_DUPLICATE_TIMESHEET`. New timesheets are `DRAFT`. Submission records `submitted_by_operator_ref` and moves the sheet to `SUBMITTED`; rejection by the host coordinator moves it to `REJECTED` — the server accepts the call without recording any accompanying payload field — and revision by the supervisor returns a `REJECTED` sheet to `DRAFT`, replacing prior values with any `day_classification`, `reported_work_minutes`, or `reported_travel_minutes` supplied in the correction.

Certification is where field time becomes money, and it is the most heavily guarded write in the program. A `HostCoordinator` certifies a `SUBMITTED` sheet by presenting a `certifier_operator_ref`, and the checks fire in the fixed order of §2.9: the caller's `X-User-ID` must match the event's `host_utility_id` (`ERR_SCOPE_MISMATCH`); the sheet must actually be `SUBMITTED` (`ERR_INVALID_STATE_TRANSITION`); the crew must stand at `CLEARED_TO_WORK` (`ERR_CREW_NOT_CLEARED` — this safety gate outranks the temporal check when both would fail); the current date must be no later than fourteen days after the `work_date` (`ERR_CERTIFICATION_WINDOW_CLOSED`); the certifier must differ from `submitted_by_operator_ref` (`ERR_SEGREGATION_OF_DUTIES`); and the effective-schedule selector must find a `PUBLISHED` or `LOCKED` schedule for the crew's event and owning utility covering the `work_date` (`ERR_NO_EFFECTIVE_SCHEDULE`). On success the sheet pins that schedule as its `certified_schedule_id`, records the certifier, and prices the day into `certified_amount_cents`.

The daily price depends on the classification and on the pinned schedule's rate line for the crew's `crew_type`; if the schedule carries no rate line for that `crew_type`, the line's `hourly_rate_cents` is treated as zero, so labor bills zero but a `STANDBY` or `WORK` day still adds the crew's `equipment_daily_total_cents`. A `REST` day bills zero — no labor and no equipment. A `TRAVEL` day bills travel time only: `reported_travel_minutes` multiplied by the line's `hourly_rate_cents` and divided by sixty, rounded half-up to whole cents — no overtime, no storm premium, and no equipment charge ever applies to a travel day. A `STANDBY` day bills a flat eight hours: 480 minutes at the base rate, divided by sixty and rounded half-up, with reported minutes ignored and no premium applied, and then the crew's `equipment_daily_total_cents` is added. A `WORK` day splits `reported_work_minutes` into three bands against the schedule's thresholds: straight-time minutes are the smaller of the reported minutes and `ot_threshold_minutes`; overtime minutes are whatever lies beyond `ot_threshold_minutes`, capped at the span between `ot_threshold_minutes` and `dt_threshold_minutes`; and double-time minutes are whatever lies beyond `dt_threshold_minutes`. A day reporting exactly the overtime threshold bills zero overtime — overtime begins strictly beyond the threshold. Each band is priced and rounded half-up to whole cents independently: straight minutes at the base rate per hour; overtime minutes at the base rate scaled by `ot_multiplier_bps` ten-thousandths (the 15000 default yields time-and-a-half); double-time minutes at the base rate scaled by `dt_multiplier_bps` ten-thousandths (20000 yields double time). The three rounded components sum to the day's labor, and when the `work_date` falls inside the event's premium window — on or after `premium_window_start`, on or before `premium_window_end` — that already-rounded labor is uplifted by `storm_premium_bps` ten-thousandths and rounded half-up once more. Equipment is added last: the day's amount is the labor figure plus `equipment_daily_total_cents`, unrounded.

Certification also synchronizes the ledgers: the request's `certified_direct_cents` and the event's `total_certified_direct_cents` — the latter summing certified timesheet amounts and approved per-diem amounts across all of the event's requests — are recomputed on the spot. When a pinned schedule is later superseded, the certification is stale: recertification, available only while the pinned schedule stands at `SUPERSEDED` (any other pin is `ERR_INVALID_STATE_TRANSITION`), re-resolves the selector against the current effective schedule, recomputes the amount under the same segregation and fourteen-day-window rules, and increments the timesheet's `version` by one. Throughout, the safety cascade's shuttle applies: a crew suspension parks the crew's `SUBMITTED` sheets in `HELD`, and the hold-release returns them to `SUBMITTED`.

Per-diem claims follow the same rhythm at the member level. The responding coordinator files a claim with the `crew_id`, the `claim_date` — unique per crew, with duplicates rejected as `ERR_DUPLICATE_CLAIM` — the `member_count`, which must be at least one and no more than the crew's `roster_size` (`ERR_INVALID_REQUEST` otherwise), the `meals_provided_count` of host-provided meals that day — the server accepts any non-negative integer without range validation, so a count above three produces a negative meal factor and hence a negative claim amount under `STANDARD` — a `day_factor_type` of `FULL` or `TRAVEL`, and, when required, `receipts_total_cents`. At creation the system resolves the effective schedule covering the `claim_date`, copies its `per_diem_method` onto the claim as `method_applied`, computes `lodging_covered` — true when the crew holds a non-cancelled lodging assignment whose stay interval contains the claim date — and prices the claim into `amount_cents`.

Pricing has two variants selected by `method_applied`, and both round half-up to whole cents per claim-day before any summation; adding unrounded daily values and rounding once at the end is forbidden. Under `STANDARD`, the raw entitlement is `member_count` times the schedule's `per_diem_rate_cents`, scaled by the day factor — a `FULL` day counts whole, a `TRAVEL` day counts three-quarters — and scaled again by the meal factor, which removes one third of the day for each host-provided meal, so three provided meals reduce the formula-based entitlement to zero; any `receipts_total_cents` supplied is ignored. Under `ACTUAL`, the raw entitlement is the receipted amount capped at one and a half times the members' standard day rate — the cap being `member_count` times `per_diem_rate_cents` times one and a half, rounded half-up before the comparison — and filing an `ACTUAL`-method claim without `receipts_total_cents` is `ERR_INVALID_REQUEST`. Claims are born `SUBMITTED`; the host coordinator approves or rejects them, approval moving a claim to `APPROVED` and recomputing the request's `certified_direct_cents` and the event's `total_certified_direct_cents`, rejection moving it to `REJECTED`. Both are terminal, and like timesheets the claims shuttle between `SUBMITTED` and `HELD` under the safety cascade.

### 3.7. Demobilization and Return

When the host no longer needs a crew, the host coordinator releases it. Release moves mobility from `ARRIVED` to `DEMOBILIZING`, stamps `released_at`, forces `readiness_status` to the terminal `RELEASED` — no further certification can occur for this crew — and fires the demobilization cascade. Its first link checks the crew out of lodging: every `OCCUPIED` assignment moves to `CHECKED_OUT` with `actual_check_out_date` set to the current date, and the block's `assigned_rooms` drops accordingly. Its second link recomputes the request's deployable count and demotes a `FULFILLED` request to `IN_PROGRESS` if the count has fallen below `required_minimum_crews`.

The journey home closes on the responding side: the owning utility's coordinator confirms the crew's return, moving mobility from `DEMOBILIZING` to `RETURNED` and stamping `returned_at`. At that moment — and only at that moment — the server checks whether every one of the request's crews has reached a terminal mobility (`RETURNED` or `WITHDRAWN`); if so the request itself is released, moving from `IN_PROGRESS` or `FULFILLED` to `RELEASED`. A withdrawal that completes the terminal-mobility set does not by itself trigger the release check: a request whose last outstanding crew is withdrawn (rather than returned) stays in `IN_PROGRESS` or `FULFILLED` until some later `complete_return` call re-evaluates the condition. `RETURNED` and `WITHDRAWN` are terminal for the crew.

### 3.8. Invoicing, Disputes, and Settlement

Billing begins once a request is underway. The responding utility's `RespondingFinance` drafts an invoice with the `request_id`, the `rate_schedule_id` to pin as the billing basis, and an inclusive `billing_period_start` to `billing_period_end` window — a start after the end is `ERR_INVALID_REQUEST`. The request must stand at `IN_PROGRESS`, `FULFILLED`, or `RELEASED` (`ERR_INVALID_STATE_TRANSITION` otherwise); the pinned schedule must belong to the request's event and responding utility, else `ERR_REFERENTIAL_INTEGRITY`; and at most one live invoice may exist per request — a second invoice while a non-`DRAFT`, non-`VOID` one exists is `ERR_INVOICE_EXISTS`. Drafting immediately computes the provisional figures: `provisional_subtotal_cents` sums the certified amounts of the period's `CERTIFIED` timesheets, a provisional pricing of the period's still-`SUBMITTED` timesheets obtained by evaluating the daily-billing rules of §3.6 on their reported minutes, the period's `APPROVED` per-diem claims, and the period's still-`SUBMITTED` claims; `provisional_fee_cents` applies the schedule's mobilization-fee tiers to that subtotal; and `provisional_total_cents` is their sum. Because uncertified rows are estimated, a provisional total legitimately diverges from the final figure computed later on identical raw rows.

Submission turns the draft into a claim on the host. The checks fire in §2.9 order: the caller's `X-User-ID` must equal the request's `responding_utility_id` (`ERR_SCOPE_MISMATCH`); the event must stand at `DEMOBILIZING` (`ERR_EVENT_NOT_DEMOBILIZING`); the current logical time must be no later than thirty days after the event's `demobilized_at` (`ERR_INVOICE_WINDOW_CLOSED`); no covered `CERTIFIED` timesheet may still be pinned to a `SUPERSEDED` schedule — such sheets must be recertified first, or the submission fails with `ERR_SUPERSEDED_SCHEDULE`; and the computed `final_total_cents` must be greater than zero, since an invoice with nothing newly billable in the period is `ERR_EMPTY_INVOICE`. The final totals count only settled rows: `labor_subtotal_cents` sums `certified_amount_cents` over the request's crews' `CERTIFIED` timesheets whose `work_date` falls inside the billing period and whose `billed_invoice_id` is still empty, and `per_diem_subtotal_cents` sums `amount_cents` over `APPROVED` claims in the period not yet swept by a non-`VOID` invoice — both inputs are sums of already-rounded integers, so no further rounding occurs. The mobilization fee is then selected from the schedule's `mobilization_fee_tiers`: sorted ascending by `min_subtotal_cents`, the applicable tier is the last tier whose threshold is at most the pre-fee direct subtotal — keyed always on the pre-fee subtotal, never on the post-fee total — and `mobilization_fee_cents` is the subtotal times that tier's `fee_bps`, divided by ten thousand, rounded half-up. `final_total_cents` is labor plus per-diem plus fee. Submission sweeps the covered rows — stamping `billed_invoice_id` on each swept timesheet and locking the swept claims to this invoice — sets `outstanding_cents` equal to `final_total_cents`, stamps `submitted_at`, and recomputes the event's `total_invoiced_cents` and the request's `invoiced_total_cents`, the latter mirroring the live invoice's final total.

Approval belongs to the host's `HostFinance`, scoped to the event's host utility, and carries the program's sharpest segregation rule: the presented `approver_operator_ref` must differ from the `certified_by_operator_ref` of every timesheet the invoice covers, so no operator who certified field time can approve its billing — a collision is `ERR_SEGREGATION_OF_DUTIES`. Approval records `approved_by_operator_ref`. Payment then settles the balance: marking paid requires a positive `amount_cents` — zero or less is `ERR_INVALID_AMOUNT` — that equals `outstanding_cents` exactly, otherwise `ERR_PAYMENT_AMOUNT_MISMATCH`. A clean payment records `amount_paid_cents`, stamps `paid_at`, drives `outstanding_cents` to zero, recomputes the event's `total_paid_cents`, and — when the underlying request already stands at `RELEASED` — closes the request, moving it from `RELEASED` to `CLOSED`.

Disputes follow their own cycle. The host finance disputes a `SUBMITTED` invoice by giving a `reason` — recorded into `dispute_reason` as one of `RATE_MISMATCH`, `HOURS_MISMATCH`, `PER_DIEM_MISMATCH`, `DUPLICATE`, or `OTHER` — and a `disputed_amount_cents` of at least one and at most the current `outstanding_cents` (`ERR_DISPUTE_AMOUNT_INVALID`). The responding finance answers with a credit proposal: `credit_cents` of at least one and at most the disputed amount (`ERR_CREDIT_EXCEEDS_DISPUTED`), recorded as `proposed_credit_cents`, moving the invoice from `DISPUTED` to `CREDIT_PROPOSED`. The host may accept the proposal — `applied_credit_total_cents` grows by the proposed credit, `outstanding_cents` shrinks by the same amount, the dispute fields are cleared, and the invoice returns to `SUBMITTED`, while `final_total_cents` and the invoiced totals stay immutable — or reject it, escalating the invoice to `ESCALATED`. An escalated dispute is settled by `ProgramAdmin` arbitration: a pinned `final_credit_cents` anywhere from zero up to the disputed amount — arbitration alone may set the credit to zero, while a proposal must be positive; anything beyond the disputed amount is `ERR_CREDIT_EXCEEDS_DISPUTED` — after which the credit is applied, `outstanding_cents` recomputed as `final_total_cents` minus `applied_credit_total_cents` minus `amount_paid_cents`, the dispute fields cleared, and the invoice returns to `SUBMITTED`.

Voiding unwinds an invoice. A `DRAFT` invoice discarded by the responding finance simply drops its provisional figures. Voiding a `SUBMITTED` invoice clears `billed_invoice_id` from every swept timesheet and recomputes the event's `total_invoiced_cents` and the request's `invoiced_total_cents` — per §2.10's compensating invariant, a submit-then-void sequence leaves both totals exactly where they were before submission. `PAID` and `VOID` are terminal.

### 3.9. After-Action Reporting and Event Close

Every event closes the loop with a single after-action report. The host coordinator opens it with the `event_id` — one report per event, a second attempt rejected with `ERR_AAR_EXISTS` — a narrative `summary`, and an optional `lessons_learned`; the report begins in `DRAFTING`. Submission requires that every crew on the event's requests has reached terminal mobility, `RETURNED` or `WITHDRAWN` — any crew still outstanding rejects the submission with `ERR_EVENT_NOT_FULLY_DEMOBILIZED` — and computes the report's four metrics. `total_crew_days` counts the event's `CERTIFIED` timesheets classified `WORK`. The report then takes two deliberate cost views: `as_certified_total_cents` is the audit view, summing certified timesheet amounts and approved per-diem amounts across the event's requests with no mobilization fee and no unresolved billing; `as_billed_total_cents` is the contractual view, summing `final_total_cents` over invoices in `APPROVED` or `PAID` status, mobilization fee included and disputed-but-unresolved invoices excluded. The two views legitimately differ on identical underlying data, and `variance_cents` records their difference, as-billed minus as-certified.

A `ProgramAdmin` accepts the report, moving it from `SUBMITTED` to `ACCEPTED`. That acceptance is one half of event closeout: closing the event — a `ProgramAdmin` action moving it from `DEMOBILIZING` to `CLOSED` — requires an `ACCEPTED` after-action report for the event and every invoice on the event's requests standing at `PAID` or `VOID`; either gap rejects the close with `ERR_EVENT_CLOSE_BLOCKED`.

## 4. Endpoint Definitions

All endpoints are mounted under `/mutual-aid`. Operations that create a new resource return `201 Created`; operations that modify or transition an existing resource return `200 OK`. Request and response payloads, side effects, and error triggers are specified in §2 and §3; the table below is a navigational summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/mutual-aid/_clock/set_current_utc` | Set the program logical clock | ProgramAdmin |
| POST | `/mutual-aid/utility-companies` | Register a participating utility company | ProgramAdmin |
| GET | `/mutual-aid/utility-companies/{id}` | Get one company | All roles |
| POST | `/mutual-aid/events` | Declare a mutual-aid event | ProgramAdmin |
| GET | `/mutual-aid/events/{id}` | Get one event | All roles |
| GET | `/mutual-aid/events` | List events | All roles |
| POST | `/mutual-aid/events/{id}/activate` | Activate an event (OPEN → ACTIVE) | ProgramAdmin |
| POST | `/mutual-aid/events/{id}/begin_demobilization` | Begin demobilization (ACTIVE → DEMOBILIZING); anchors the 30-day invoice window and seals intake | HostCoordinator |
| POST | `/mutual-aid/events/{id}/close` | Close an event (DEMOBILIZING → CLOSED) | ProgramAdmin |
| POST | `/mutual-aid/billing-rate-schedules` | Create a rate schedule for an event and the caller's responding utility | RespondingCoordinator |
| GET | `/mutual-aid/billing-rate-schedules/{id}` | Get one schedule | All roles |
| GET | `/mutual-aid/billing-rate-schedules` | List schedules | All roles |
| POST | `/mutual-aid/billing-rate-schedules/{id}/publish` | Publish a schedule (DRAFT → PUBLISHED), optionally superseding a predecessor with OCC | RespondingCoordinator |
| POST | `/mutual-aid/billing-rate-schedules/{id}/lock` | Lock a published schedule (PUBLISHED → LOCKED) | HostFinance |
| POST | `/mutual-aid/assistance-requests` | Create a resource-typed assistance request to a responding utility | HostCoordinator |
| GET | `/mutual-aid/assistance-requests/{id}` | Get one request | All roles |
| GET | `/mutual-aid/assistance-requests` | List requests | All roles |
| POST | `/mutual-aid/assistance-requests/{id}/submit` | Submit a draft, or resubmit amended terms from COUNTERED | HostCoordinator |
| POST | `/mutual-aid/assistance-requests/{id}/counter` | Counter a submitted request with counter-terms | RespondingCoordinator |
| POST | `/mutual-aid/assistance-requests/{id}/accept` | Accept a submitted request (requires a published/locked schedule) | RespondingCoordinator |
| POST | `/mutual-aid/assistance-requests/{id}/decline` | Decline a submitted or countered request | RespondingCoordinator |
| POST | `/mutual-aid/assistance-requests/{id}/cancel` | Cancel a draft, submitted, or countered request | HostCoordinator |
| POST | `/mutual-aid/crews` | Commit a crew (roster and equipment inventory) to a request | RespondingCoordinator |
| GET | `/mutual-aid/crews/{id}` | Get one crew | All roles |
| GET | `/mutual-aid/crews` | List crews | All roles |
| POST | `/mutual-aid/crews/{id}/confirm_arrival` | Confirm crew arrival (COMMITTED → ARRIVED); fires the arrival cascade | HostCoordinator |
| POST | `/mutual-aid/crews/{id}/release` | Release a crew (ARRIVED → DEMOBILIZING); fires the demobilization cascade | HostCoordinator |
| POST | `/mutual-aid/crews/{id}/complete_return` | Confirm crew return (DEMOBILIZING → RETURNED); last crew out releases the request | RespondingCoordinator |
| POST | `/mutual-aid/crews/{id}/withdraw` | Withdraw a committed crew before arrival (COMMITTED → WITHDRAWN) | RespondingCoordinator |
| POST | `/mutual-aid/crews/{id}/suspend` | Suspend a crew on safety grounds (CLEARED_TO_WORK → SAFETY_HOLD) | HostSafetyOfficer |
| POST | `/mutual-aid/safety-briefings` | Conduct a host-rules safety briefing for a crew (created CONDUCTED) | HostSafetyOfficer |
| GET | `/mutual-aid/safety-briefings/{id}` | Get one briefing | All roles |
| GET | `/mutual-aid/safety-briefings` | List briefings | All roles |
| POST | `/mutual-aid/safety-briefings/{id}/acknowledge` | Acknowledge a briefing (CONDUCTED → ACKNOWLEDGED); crew becomes CLEARED_TO_WORK | CrewSupervisor |
| POST | `/mutual-aid/timesheets` | Draft a daily timesheet for a crew | CrewSupervisor |
| GET | `/mutual-aid/timesheets/{id}` | Get one timesheet | All roles |
| GET | `/mutual-aid/timesheets` | List timesheets | All roles |
| POST | `/mutual-aid/timesheets/{id}/submit` | Submit a draft timesheet (DRAFT → SUBMITTED) | CrewSupervisor |
| POST | `/mutual-aid/timesheets/{id}/certify` | Certify a timesheet (SUBMITTED → CERTIFIED); pins the effective schedule and prices the day | HostCoordinator |
| POST | `/mutual-aid/timesheets/{id}/recertify` | Re-pin and re-price a certified timesheet whose pinned schedule was superseded | HostCoordinator |
| POST | `/mutual-aid/timesheets/{id}/reject` | Reject a submitted timesheet (SUBMITTED → REJECTED) | HostCoordinator |
| POST | `/mutual-aid/timesheets/{id}/revise` | Revise a rejected timesheet back to DRAFT with corrected values | CrewSupervisor |
| POST | `/mutual-aid/lodging-blocks` | Register a hotel room block | HostCoordinator |
| GET | `/mutual-aid/lodging-blocks/{id}` | Get one block | All roles |
| GET | `/mutual-aid/lodging-blocks` | List blocks | All roles |
| POST | `/mutual-aid/lodging-assignments` | Allocate rooms from a block to a crew | HostCoordinator |
| GET | `/mutual-aid/lodging-assignments/{id}` | Get one assignment | All roles |
| GET | `/mutual-aid/lodging-assignments` | List assignments | All roles |
| POST | `/mutual-aid/lodging-assignments/{id}/cancel` | Cancel a reserved assignment (RESERVED → CANCELLED), freeing capacity | HostCoordinator |
| POST | `/mutual-aid/per-diem-claims` | File a daily per-diem claim priced under the effective schedule's method | RespondingCoordinator |
| GET | `/mutual-aid/per-diem-claims/{id}` | Get one claim | All roles |
| GET | `/mutual-aid/per-diem-claims` | List claims | All roles |
| POST | `/mutual-aid/per-diem-claims/{id}/approve` | Approve a claim (SUBMITTED → APPROVED) | HostCoordinator |
| POST | `/mutual-aid/per-diem-claims/{id}/reject` | Reject a claim (SUBMITTED → REJECTED) | HostCoordinator |
| POST | `/mutual-aid/invoices` | Draft an invoice against a request; provisional totals computed immediately | RespondingFinance |
| GET | `/mutual-aid/invoices/{id}` | Get one invoice | All roles |
| GET | `/mutual-aid/invoices` | List invoices | All roles |
| POST | `/mutual-aid/invoices/{id}/submit` | Submit an invoice (DRAFT → SUBMITTED); computes final totals and sweeps certified rows | RespondingFinance |
| POST | `/mutual-aid/invoices/{id}/approve` | Approve a submitted invoice with segregation-of-duties against covered certifiers | HostFinance |
| POST | `/mutual-aid/invoices/{id}/mark_paid` | Mark an approved invoice paid; amount must equal the outstanding balance exactly | HostFinance |
| POST | `/mutual-aid/invoices/{id}/void` | Void a draft or submitted invoice, compensating its effects | RespondingFinance |
| POST | `/mutual-aid/invoices/{id}/dispute` | Dispute a submitted invoice (SUBMITTED → DISPUTED) | HostFinance |
| POST | `/mutual-aid/invoices/{id}/propose_credit` | Propose a credit on a disputed invoice (DISPUTED → CREDIT_PROPOSED) | RespondingFinance |
| POST | `/mutual-aid/invoices/{id}/accept_credit` | Accept a proposed credit (CREDIT_PROPOSED → SUBMITTED); credit applied to outstanding | HostFinance |
| POST | `/mutual-aid/invoices/{id}/reject_credit` | Reject a proposed credit (CREDIT_PROPOSED → ESCALATED) | HostFinance |
| POST | `/mutual-aid/invoices/{id}/arbitrate` | Arbitrate an escalated dispute with a pinned credit (ESCALATED → SUBMITTED) | ProgramAdmin |
| POST | `/mutual-aid/after-action-reports` | Open the event's after-action report (one per event) | HostCoordinator |
| GET | `/mutual-aid/after-action-reports/{id}` | Get one report | All roles |
| GET | `/mutual-aid/after-action-reports` | List reports | All roles |
| POST | `/mutual-aid/after-action-reports/{id}/submit` | Submit a report (DRAFTING → SUBMITTED); computes cost-variance metrics | HostCoordinator |
| POST | `/mutual-aid/after-action-reports/{id}/accept` | Accept a report (SUBMITTED → ACCEPTED); unblocks event close | ProgramAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue is the identifier-to-status reference.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_SCOPE_MISMATCH` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_INVALID_AMOUNT` | 400 Bad Request |
| `ERR_EVENT_NOT_ACCEPTING_REQUESTS` | 409 Conflict |
| `ERR_EVENT_NOT_DEMOBILIZING` | 409 Conflict |
| `ERR_EVENT_CLOSE_BLOCKED` | 409 Conflict |
| `ERR_EVENT_NOT_FULLY_DEMOBILIZED` | 409 Conflict |
| `ERR_SCHEDULE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_SCHEDULE_NOT_PUBLISHED` | 409 Conflict |
| `ERR_NO_EFFECTIVE_SCHEDULE` | 409 Conflict |
| `ERR_STALE_SCHEDULE_VERSION` | 412 Precondition Failed |
| `ERR_SUPERSEDED_SCHEDULE` | 409 Conflict |
| `ERR_LODGING_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_LODGING_OVERLAP` | 409 Conflict |
| `ERR_CREW_NOT_CLEARED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_DUPLICATE_TIMESHEET` | 409 Conflict |
| `ERR_DUPLICATE_CLAIM` | 409 Conflict |
| `ERR_CERTIFICATION_WINDOW_CLOSED` | 409 Conflict |
| `ERR_MOBILIZATION_DEADLINE_PASSED` | 409 Conflict |
| `ERR_INVOICE_WINDOW_CLOSED` | 409 Conflict |
| `ERR_INVOICE_EXISTS` | 409 Conflict |
| `ERR_EMPTY_INVOICE` | 409 Conflict |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 409 Conflict |
| `ERR_DISPUTE_AMOUNT_INVALID` | 409 Conflict |
| `ERR_CREDIT_EXCEEDS_DISPUTED` | 409 Conflict |
| `ERR_AAR_EXISTS` | 409 Conflict |
| `ERR_REFERENTIAL_INTEGRITY` | 409 Conflict |

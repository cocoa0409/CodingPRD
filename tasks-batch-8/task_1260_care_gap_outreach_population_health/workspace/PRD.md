# Care Gap Outreach & Population Health API — Product Requirements Document

## 1. Introduction

Population health programs live and die by follow-through: a screening measure is only as good as the registry that identifies who is overdue, the outreach engine that contacts them, and the reconciliation loop that proves the gap actually closed. Today these concerns are scattered across spreadsheets, dialer exports, and claims warehouses, which makes it impossible to answer basic questions — which members are overdue for a colonoscopy, how many times have we called them, did the ride we booked ever happen, and what did that closure earn the panel manager — without manual detective work.

This document specifies a single API, mounted under `/population-health`, that runs the full care-gap outreach lifecycle for a population health department. It covers registry cohort definition and stratification, gap identification for screening and medication-adherence measures with priority scoring, multi-channel outreach campaigns with attempt cadence rules, appointment scheduling with transportation assistance, gap-closure documentation with independent quality review, exclusion and refusal handling, panel manager workload and incentive computation, and measure performance reporting with a provisional/final reconciliation model. Time inside the system is driven by a logical registry clock rather than wall-clock time, so that measurement windows, reporting lags, and cadence cooldowns are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, identifying the role under which that operator acts. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not permitted to invoke the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The role vocabulary is fixed and spelled exactly as follows:

- `ProgramAdministrator` — the population-health program administrator; owns registries, measures, cohorts, panels, campaigns, the logical clock, workload tracking rows, incentive payouts, and performance reports. When `X-User-Role` is `ProgramAdministrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.
- `PanelManager` — the care-gap outreach worker who records attempts, books appointments, and shepherds gaps to closure. When `X-User-Role` is `PanelManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted member entity; it is the value recorded as `panel_manager_id` on the panels that manager owns and on the workload rows that track that manager, and panel-level ownership is scoped by it.
- `QualityReviewer` — the independent reviewer who approves or rejects closure evidence and adjudicates exclusion requests. When `X-User-Role` is `QualityReviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; segregation-of-duties rules compare it against the submitter's captured identity rather than against any entity `id`.
- `TransportationCoordinator` — the vendor-facing coordinator who arranges, completes, and cancels transportation assists. When `X-User-Role` is `TransportationCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `DataReconciliationBot` — the system actor that processes the claims feed and reopens mismatched gaps. When `X-User-Role` is `DataReconciliationBot`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10, must be at least 1, and may not exceed 100. The `offset` defaults to 0. List responses are sorted by `created_at` ascending, and the `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix. With one exception noted below, every resource also carries `created_at` and `updated_at` — ISO 8601 UTC timestamps rendered with three fractional digits — and an integer `version` that starts low and increments by one on every mutation of that resource. The exception is the outreach attempt record, which is an append-only ledger entry: it carries only `id` and `created_at`, and both `updated_at` and `version` are absent from it.

### 2.5. The Registry Logical Clock

Each registry runs on its own logical business clock, exposed as the registry's `current_business_date`. When a registry is created, its clock initializes to `2026-05-01T00:00:00Z`, and from then on time only moves forward through an administrator-only clock-advance capability that accepts a `registry_id` and a target instant `to_iso8601` and sets the registry's `current_business_date` to that instant. This capability is the only way time moves; nothing in the system reads wall-clock time.

Advancing the clock is not inert bookkeeping. As the clock crosses meaningful instants, the system fires the transitions that depend on them: a care gap whose reconciliation window has lapsed expires, a scheduled campaign whose `starts_at` has been reached launches automatically, an active campaign whose `ends_at` has been crossed completes automatically, and a reopened gap whose `next_eligible_attempt_at` has been reached is re-triaged back into the open pool. All temporal validation rules in this document — cadence cooldowns, campaign windows, slot validity, evidence windows, reporting lags — evaluate against `current_business_date`.

### 2.6. Numeric Precision, Rounding, and Monetary Conventions

Scores, rates, and money each have a pinned precision. Priority scores are integers; after the scoring sum is clamped into its allowed range, any fractional residue is floored away. Utilization ratios are numbers with exactly four decimal places, rounded half up. Closure rates are integer basis points, rounded half up. All monetary amounts are integer cents, rounded half up; where a payout multiplies a per-gap rate by a count, the per-gap line is rounded to whole cents first and only then multiplied — rounding per line and then summing is the pinned order, never sum-then-round. Cadence arithmetic produces datetimes at second precision.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and both take their version field as a non-optional input.

Rebuilding a panel requires the request to carry `expected_panel_version` holding the caller's last observed `version` of that panel. If the panel's current `version` has advanced beyond what the caller observed — because another writer triggered a rebuild or any other mutation in the meantime — the rebuild is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the caller from rebuilding on top of a panel state it never saw.

Recording an outreach attempt against a care gap requires the request to carry `expected_care_gap_version` holding the caller's last observed `version` of that gap. If the gap's current `version` has advanced since — for example because a prior attempt already moved `attempt_count` and `next_eligible_attempt_at` — the attempt is rejected with `ERR_STALE_VERSION` (HTTP 412), since the caller's cadence computation was made against a stale record.

No other endpoint accepts a version field.

### 2.8. Validation Order and Error Precedence

When several checks could reject the same request, they are evaluated in a fixed global order, and the first failure wins. Malformed bodies, missing required fields, and type mismatches are rejected with `ERR_INVALID_REQUEST` (HTTP 400) as the request is parsed. The precedence chain for well-formed requests is: first the identity headers (failure yields `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), then role permission for the endpoint (failure yields `ERR_INSUFFICIENT_PERMISSIONS`), then existence of every resource identifier in the path, evaluated left to right (failure yields `ERR_NOT_FOUND`, HTTP 404), then whether the target resource is in a state that permits the action (failure yields `ERR_INVALID_STATE`, HTTP 409), then the optimistic-concurrency check where one applies (failure yields `ERR_STALE_VERSION`), and only then the business rules in their own ascending priority order — cadence timing before campaign window, campaign window before consent, consent before the attempt cap, the cap before exclusion screening, exclusion screening before campaign liveness. The per-endpoint business-rule chains appear alongside the workflows they guard in §3.

### 2.9. Nested Paths and Filtered Listing

Where a URL nests a child beneath a parent, path identifiers are validated left to right: a parent that does not exist yields `ERR_NOT_FOUND` before the child segment is ever examined, and a child that does not exist beneath an existing parent likewise yields `ERR_NOT_FOUND`. Alongside the nested routes, the API offers flat list endpoints for every operational resource so that records remain reachable by foreign key when the caller does not know the owning hierarchy — for example, care gaps filterable by `panel_id`, `member_id`, or `measure_id`, and outreach attempts filterable by `care_gap_id`, `campaign_id`, or `member_id`. All list endpoints, nested or flat, share the pagination contract of §2.3.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Registry: Measures, Cohorts, and Members

A `ProgramAdministrator` begins by creating a registry with a display `name`, an optional `description`, and a `program_year` identifying the measurement year; the program year is immutable once the registry exists. A new registry is immediately `ACTIVE` and its logical clock starts at the instant described in §2.5. The registry status vocabulary is `ACTIVE` and `ARCHIVED`.

Within a registry, the administrator defines quality measures. Each measure carries a `measure_code` unique within its registry (for example, a colorectal screening code), a `measure_domain` of either `SCREENING` or `MED_ADHERENCE`, and a `lookback_days` value stating how many days of history satisfy the gap — a colonoscopy measure might look back 3650 days. Two timing knobs have defaults: `exclusion_window_days`, the number of days an approved exclusion suppresses the gap from the reporting denominator, defaults to 90; and `reporting_lag_days`, the number of days after period end that must elapse before the final report variant may be published, defaults to 30. A measure is created in `DRAFT` status and becomes available for panel construction only after the administrator publishes it, moving it to `PUBLISHED`; the full status vocabulary is `DRAFT`, `PUBLISHED`, and `RETIRED`.

Cohort definitions stratify the registry population. A cohort carries a `cohort_code` unique within its registry, inclusive age bounds `min_age` and `max_age`, a `risk_tier_filter` of `ANY`, `LOW`, `MEDIUM`, or `HIGH`, and a `requires_active_enrollment` flag that defaults to true and demands that a member be enrolled at evaluation time to match. Cohorts are born in `DRAFT` status, and the administrator activates one to move it to `ACTIVE`; the vocabulary also includes `RETIRED`.

Members are registered into a registry with a medical record number `mrn` that is unique within the registry, a `date_of_birth`, a `risk_tier` of `LOW`, `MEDIUM`, or `HIGH`, and two consent flags: `phone_ok`, gating call and text outreach, and `mail_ok`, gating postal outreach; both default to true. Registration leaves the member's `enrollment_status` as `ENROLLED` — the enrollment vocabulary also includes `DISENROLLED` and `DECEASED` — and the denormalized `open_gap_count` begins at zero. Member rosters can be listed with `risk_tier` and `enrollment_status` filters in addition to the standard pagination parameters.

### 3.2. Panels and Gap Materialization

Panels are the working unit of the outreach program: a panel materializes one cohort evaluated against one measure, owned by one panel manager. An administrator creates a panel by supplying a `cohort_id`, a `measure_id`, and the owning manager's `panel_manager_id`; the panel is born in `BUILDING` status. Activation requires the panel to be in `BUILDING`, the referenced cohort to be `ACTIVE`, and the referenced measure to be `PUBLISHED`. Upon activation the system materializes a care gap for every member who matches the cohort — age within the inclusive bounds, risk tier matching the filter (with `ANY` matching every tier), and enrollment active when the cohort requires it — and who lacks a qualifying event inside the measure's lookback window. The panel's `member_count` is computed as the cardinality of members currently satisfying the cohort criteria, and the panel moves to `ACTIVE`.

Each materialized care gap records its `panel_id`, `member_id`, and `measure_id`, plus the member's `last_qualifying_event_at` — the date of the last qualifying screening or adherence event, or null when the member has never had one. From these the system computes the gap's `due_date`: when a qualifying event exists, the due date is that event's date plus the measure's `lookback_days`; when `last_qualifying_event_at` is null, the due date falls back to the member's enrollment date.

Panels evolve. A rebuild request — which must carry `expected_panel_version` per §2.7 — moves an `ACTIVE` panel to `REBUILDING`, increments the panel's `version` by one, and materializes new care gaps for newly eligible members while leaving existing gaps untouched. Finalizing the rebuild returns the panel to `ACTIVE`. Retirement is permitted from either `ACTIVE` or `REBUILDING` and moves the panel to its terminal `RETIRED` status: no new care gaps are created under a retired panel, and existing care gaps are unaffected. Panels are listable within a registry or across registries through the flat list endpoint, with `panel_manager_id`, `cohort_id`, and `measure_id` filters available, and each panel exposes its care gaps through a nested listing filterable by `status` and `priority_band`.

### 3.3. Gap Triage: Due Dates, Overdue Days, and Priority Scoring

Every care gap flows through the status vocabulary `OPEN`, `OUTREACH_IN_PROGRESS`, `AWAITING_APPOINTMENT`, `PENDING_EVIDENCE`, `CLOSED`, `REOPENED`, `EXCLUDED`, and `EXPIRED`, of which only `EXPIRED` is terminal. A gap is born `OPEN` at panel activation. The member's denormalized `open_gap_count` tracks how many of that member's gaps sit in `OPEN`, `OUTREACH_IN_PROGRESS`, `AWAITING_APPOINTMENT`, or `PENDING_EVIDENCE`.

Two computed quantities drive triage. `days_overdue` is the number of whole days by which `current_business_date` has passed the gap's `due_date`, floored at zero so a gap not yet due reports zero. `priority_score` is an integer from 0 to 100 computed from five terms, summed and then clamped into that range with any fraction floored away after clamping. The first term is the overdue contribution: the gap's `days_overdue` capped at 90 days, so no gap earns more than 90 points from age alone. The second term is the clinical weight: the member's risk tier contributes a weight of 1 for `LOW`, 2 for `MEDIUM`, or 3 for `HIGH`, the measure's domain contributes a weight of 1 for `SCREENING` or 2 for `MED_ADHERENCE`, and the product of the two weights is multiplied by 5. The third term is the outreach decay: 20 points minus 4 points per recorded outreach attempt, floored at zero, so unworked gaps rise to the top and heavily worked gaps sink. The fourth term is the no-show strike bonus: 8 points for every appointment under this gap that ended in a no-show. The fifth term is the reopen bonus: 12 points, but only if the gap has at some point been reopened from closure. The raw sum of these five terms is clamped so it never falls below 0 or exceeds 100.

The score maps onto a `priority_band`: a score of 80 or more is `P1_URGENT`, at least 60 but below 80 is `P2_HIGH`, at least 30 but below 60 is `P3_ROUTINE`, and below 30 is `P4_LOW`. Scores are recomputed at gap creation, whenever an outreach attempt is recorded, whenever an appointment ends in a no-show, when a gap is reopened, and when an exclusion is revoked. Gaps in `EXCLUDED` or `EXPIRED` status are exempt from recomputation and keep their last computed score. Care gaps are listable per member, per panel, or through the flat list endpoint with `status`, `priority_band`, `panel_id`, `member_id`, and `measure_id` filters. A gap's `closure_source` — `EVIDENCE`, `APPOINTMENT_COMPLETED`, or `CLAIMS_FEED` — is null until the gap closes.

### 3.4. Campaigns and the Outreach Cadence

Outreach campaigns configure how a panel's gaps are worked. An administrator creates a campaign in `DRAFT` status by supplying the target `panel_id` and `measure_id`, a campaign `name`, a `channel` of `CALL`, `TEXT`, or `MAIL`, and the campaign window: `starts_at` inclusive and `ends_at` exclusive. Four tuning knobs carry defaults — `quiet_hours_start_min` defaults to 1260 minutes from local midnight (21:00, after which outreach is blocked), `quiet_hours_end_min` defaults to 480 minutes (08:00, before which outreach is blocked), `min_attempt_interval_hours` defaults to 72 hours of per-member per-channel cooldown between attempts, and `max_attempts_per_member` defaults to 5.

The campaign lifecycle runs `DRAFT` → `SCHEDULED` → `ACTIVE`, with a pause loop and two endings. Scheduling validates the window: `starts_at` must be strictly before `ends_at`, otherwise the request fails with `ERR_INVALID_CAMPAIGN_WINDOW` (HTTP 400), and `ends_at` must still lie in the future of `current_business_date`, otherwise the request fails with `ERR_CAMPAIGN_WINDOW_PAST`. Launching — performed manually by an administrator, or automatically by the system when the clock reaches `starts_at` — requires that the clock has reached `starts_at` (otherwise `ERR_CAMPAIGN_NOT_YET_OPEN`) and that the linked panel is `ACTIVE` (otherwise `ERR_PANEL_NOT_ACTIVE`); only on launch do outreach attempts become acceptable for gaps under the campaign's panel. An `ACTIVE` campaign can be paused, and a `PAUSED` campaign can be resumed provided `ends_at` has not yet passed — resuming after the window closed fails with `ERR_CAMPAIGN_WINDOW_PAST`. A campaign completes either when an administrator completes it or when the clock crosses `ends_at`, from either `ACTIVE` or `PAUSED`; completion is gentle, and gaps still in `OUTREACH_IN_PROGRESS` under the campaign remain there with no forced transition. Cancellation is available from `DRAFT`, `SCHEDULED`, `ACTIVE`, or `PAUSED` and moves the campaign to `CANCELLED`, after which no further attempts are accepted. Campaigns are listable within a registry or flat, with `status`, `panel_id`, and `measure_id` filters.

Recording an outreach attempt is the panel manager's core action, and it is the most heavily guarded write in the system. The payload names the `campaign_id` and `channel`, the `outcome` — one of `CONTACTED`, `LEFT_MESSAGE`, `NO_ANSWER`, `BAD_ADDRESS`, `REFUSED`, or `REVERSED` — the concurrency token `expected_care_gap_version`, an optional free-text `notes`, and a `reversal_reason` that is required whenever the outcome is `REVERSED`. The checks fire in this strict order: identity headers, role permission, path existence, gap state, the stale-version check of §2.7, then cadence timing — the attempt is rejected with `ERR_ATTEMPT_TOO_EARLY` when `current_business_date` has not yet reached the gap's `next_eligible_attempt_at` — then the campaign window rule, which rejects with `ERR_CAMPAIGN_WINDOW_VIOLATION` when the attempt falls outside the campaign's `[starts_at, ends_at)` window or inside its quiet hours, then channel consent, which rejects with `ERR_CHANNEL_CONSENT_MISSING` (HTTP 403) when `phone_ok` is false and the channel is `CALL` or `TEXT`, or when `mail_ok` is false and the channel is `MAIL`, then the attempt cap, which rejects with `ERR_ATTEMPT_CAP_REACHED` once the gap's `attempt_count` has reached the campaign's `max_attempts_per_member`, then exclusion screening, which rejects with `ERR_MEMBER_EXCLUDED` when an approved exclusion covering the measure is in force for the member at `current_business_date`, and finally campaign liveness, which rejects with `ERR_CAMPAIGN_NOT_ACTIVE` unless the referenced campaign is `ACTIVE`.

A recorded attempt is stamped `attempted_at` from the registry's logical clock and denormalizes the `member_id` from its parent gap at write time. The first non-`REVERSED` attempt moves the gap from `OPEN` to `OUTREACH_IN_PROGRESS`; further attempts are a self-loop within `OUTREACH_IN_PROGRESS`. Each non-`REVERSED` attempt increments the gap's `attempt_count` by one, recomputes `next_eligible_attempt_at` via the cadence rule below, recomputes `priority_score`, and increments the gap's `version`. An attempt whose outcome is `REVERSED` — a correction to a previously misrecorded contact, justified by `reversal_reason` — is excluded from `attempt_count` and does not drive the open-to-in-progress transition. Attempts are listable per gap or through the flat list endpoint.

The cadence rule pins its evaluation order to break what would otherwise be a circular dependency between priority and scheduling. Step one picks the working channel from the gap's priority band as it stood before the attempt: `P1_URGENT` and `P2_HIGH` gaps are worked by `CALL`, `P3_ROUTINE` by `TEXT`, and `P4_LOW` by `MAIL`. Step two takes the cooldown from the campaign's `min_attempt_interval_hours`. Step three forms the candidate instant by adding the cooldown to `current_business_date`, then clips it into waking hours: if the candidate's local time-of-day is at or after `quiet_hours_start_min`, the candidate moves to `quiet_hours_end_min` on the next local day; if it is before `quiet_hours_end_min`, it moves to `quiet_hours_end_min` on the same local day. Step four sets `next_eligible_attempt_at` to the later of the clipped candidate and the campaign's `starts_at`.

### 3.5. Appointments and Transportation

When outreach succeeds, the panel manager books the member in. Scheduling an appointment against a care gap takes a `provider_id` — an opaque provider identifier — plus `slot_start_at` and `slot_end_at`, and optionally `provider_capacity_per_slot`, the aggregate capacity that provider supports per overlapping slot, which defaults to 1 and thereby governs how much overbooking is tolerated. The gap must be in `OPEN` or `OUTREACH_IN_PROGRESS`; anything else fails the state check with `ERR_INVALID_STATE`. The business checks then fire in priority order: exclusion screening rejects with `ERR_MEMBER_EXCLUDED` when an approved exclusion covers the measure for this member; uniqueness rejects with `ERR_APPOINTMENT_ALREADY_ACTIVE` when another appointment for this same gap is already in `SCHEDULED` or `CONFIRMED`; capacity rejects with `ERR_PROVIDER_SLOT_FULL` when the new window would push the count of overlapping appointments for that provider to or beyond the provider's per-slot capacity; and slot validity rejects with `ERR_INVALID_SLOT` (HTTP 400) when `slot_start_at` is not strictly before `slot_end_at` or when `slot_start_at` lies in the past relative to `current_business_date`. A successfully scheduled appointment is born `SCHEDULED`, the gap moves to `AWAITING_APPOINTMENT`, and the gap's `attempt_count` is unchanged by the booking.

The appointment lifecycle allows a confirmation path, a cyclic reschedule, and three endings. Confirming moves `SCHEDULED` to `CONFIRMED`; when a transportation assist exists for the appointment, confirmation is blocked unless the assist is `ARRANGED`, failing with `ERR_TRANSPORT_NOT_ARRANGED`. Rescheduling is cyclic: from `SCHEDULED` it is a self-loop that simply updates the slot fields, while from `CONFIRMED` it is a back-transition that reverts the appointment to `SCHEDULED` so it must be confirmed again; either way the new slot must pass the same capacity and slot-validity checks, the slot fields are updated, and the appointment's `version` increments. Cancellation is permitted from `SCHEDULED` or `CONFIRMED` with an optional `reason`, moves the appointment to `CANCELLED`, reverts the gap from `AWAITING_APPOINTMENT` to `OUTREACH_IN_PROGRESS`, and cascades any linked transportation assist in `REQUESTED` or `ARRANGED` to `CANCELLED`.

Marking a no-show requires the appointment to be in `SCHEDULED` or `CONFIRMED` and the clock to have strictly passed `slot_end_at` — attempting to mark a no-show before the slot has ended fails with `ERR_CANNOT_MARK_FUTURE_APPOINTMENT`. A no-show sets the appointment to `NO_SHOW`, reverts the gap to `OUTREACH_IN_PROGRESS` with its `priority_score` recomputed including the 8-point no-show strike bonus, cancels any linked transportation assist in `REQUESTED` or `ARRANGED`, and appends an automatic outreach attempt with channel `CALL`, outcome `NO_ANSWER`, and `notes` set to `auto:no-show`; this auto-attempt increments the gap's `attempt_count` by one and therefore counts toward cadence and the attempt cap.

Completing an appointment requires it to be `CONFIRMED` — completing anything else fails with `ERR_APPOINTMENT_NOT_CONFIRMED` — and, when a transportation assist exists, requires that assist to be `ARRANGED` or `COMPLETED`, failing with `ERR_TRANSPORT_NOT_ARRANGED` otherwise. Completion sets the appointment to `COMPLETED`, auto-creates a closure-evidence record with `evidence_type` `CHART_REVIEW`, `service_date` equal to the appointment's `slot_start_at`, and status `SUBMITTED`, pre-sets the gap's `closure_source` to `APPOINTMENT_COMPLETED` pending evidence approval, and moves the gap from `AWAITING_APPOINTMENT` to `PENDING_EVIDENCE`. Appointments are listable per gap or flat, with `status`, `care_gap_id`, `member_id`, and `provider_id` filters.

Transportation assists attach to appointments. Either a `PanelManager` or a `TransportationCoordinator` requests one by supplying a `vendor`, a planned `pickup_at`, and a `cost_cents` in cents; a negative cost is rejected with `ERR_INVALID_COST` (HTTP 400). The assist is born `REQUESTED`; the coordinator arranges it (`REQUESTED` → `ARRANGED`), completes it (`ARRANGED` → `COMPLETED`, permitted only once the parent appointment is itself `COMPLETED`), or cancels it from `REQUESTED` or `ARRANGED` with an optional `reason`. Assists are also cancelled automatically by the appointment-level cascades described above. Each assist carries its `appointment_id` and a denormalized `member_id`, and assists are listable per appointment or flat with `appointment_id`, `member_id`, and `status` filters.

### 3.6. Evidence, Closure, and Segregation of Duties

A gap closes on evidence, and evidence is judged by someone other than its submitter. Closure evidence is submitted against a care gap by a `PanelManager` or a `QualityReviewer` with an `evidence_type` of `CHART_REVIEW`, `CLAIMS_FEED`, `MEMBER_ATTESTATION`, or `LAB_RESULT`, a `service_date` recording when the qualifying service occurred, and a `document_uri` pointing at the supporting document. Submission stamps `submitted_by_role` from the caller's `X-User-Role`, births the evidence in `SUBMITTED` status, and moves the gap — which must be in `OPEN` or `OUTREACH_IN_PROGRESS`, with anything else failing the state check — into `PENDING_EVIDENCE`.

Approval is exclusive to `QualityReviewer` and enforces three checks in order: the evidence must be `SUBMITTED`; segregation of duties forbids the approver's `X-User-ID` from matching the submitter's, failing with `ERR_SOD_VIOLATION` (HTTP 403); and the `service_date` must fall inside the measure's lookback window — a service date older than `current_business_date` minus the measure's `lookback_days` fails with `ERR_EVIDENCE_OUT_OF_WINDOW`. Approval accepts optional `notes`. An approved record becomes `APPROVED`, the gap becomes `CLOSED`, and the gap's `closure_source` is set to `EVIDENCE` — or to `APPOINTMENT_COMPLETED` when the evidence derived from a completed appointment; gaps closed on the strength of claims-feed submissions record `closure_source` as `CLAIMS_FEED`. The closure then cascades outward: the member's `open_gap_count` decrements by one, the workload row of the panel's owner increments `closed_gap_count_period` by one, that workload's `utilization_ratio` is recomputed, every `PROJECTED` incentive payout for the current `period_key` is recomputed under the payout rule of §3.9, and the current period's `PROVISIONAL` performance report recomputes its `numerator_count` and `closure_rate_bps`.

Rejection takes a mandatory `rejection_reason`, is likewise exclusive to `QualityReviewer` and bound by the same segregation-of-duties rule against the submitter, sets the evidence to `REJECTED`, reverts the gap to `OUTREACH_IN_PROGRESS`, and clears the gap's `closure_source` back to null. Both `APPROVED` and `REJECTED` are terminal for the evidence record. Evidence is listable per gap or flat, with `status`, `care_gap_id`, and `member_id` filters.

### 3.7. Exclusions, Refusals, and Disenrollment

Not every open gap should be worked: contraindications, refusals, hospice, and death all legitimately remove a member from a measure's denominator. An exclusion request is submitted against a member by a `PanelManager` or a `ProgramAdministrator` with an optional `measure_id` — null means the request applies to all measures — an `exclusion_kind` of `MEDICAL_CONTRAINDICATION`, `MEMBER_REFUSAL`, `HOSPICE`, or `DECEASED`, a free-text `justification`, an `effective_from` start of the suppression window, and an optional `effective_until` whose null value makes the suppression indefinite. When the kind is `MEDICAL_CONTRAINDICATION`, the justification must be at least 20 characters long, failing with `ERR_INSUFFICIENT_JUSTIFICATION` (HTTP 400) otherwise. The request is born `SUBMITTED`; a `QualityReviewer` moves it to `UNDER_REVIEW`, and from there either approves or denies it.

Approval runs its checks in order: the request must be `UNDER_REVIEW`; segregation of duties forbids the approver being the submitter, failing with `ERR_SOD_VIOLATION`; and the member must have no appointment in `SCHEDULED` or `CONFIRMED` referencing a care gap for the measure in question, failing with `ERR_EXCLUSION_BLOCKED_BY_APPOINTMENT` — a booked appointment must be resolved before the member can be excluded. Approval takes optional `notes`, transitions every care gap for the member that matches the measure (or all of the member's gaps when `measure_id` is null) and currently sits in `OPEN` or `OUTREACH_IN_PROGRESS` to `EXCLUDED`, cancels any appointment in `SCHEDULED` or `CONFIRMED` attached to those gaps, decrements the member's `open_gap_count` by the number of gaps transitioned, and decrements the `PROVISIONAL` report denominator. Denial takes a mandatory `rejection_reason`, is bound by the same segregation-of-duties rule, and moves the request to `DENIED` with no effect on gaps. The terminal vocabulary is `APPROVED`, `DENIED`, and `REVOKED`.

While an approved exclusion is in force it suppresses the member's gaps from the reporting denominator — for the measure's `exclusion_window_days` (90 days by default), and in rate computation any approved exclusion whose `[effective_from, effective_until)` window overlaps the reporting period removes the member from the denominator. An approved exclusion also blocks new outreach attempts and new appointment bookings for the covered measure with `ERR_MEMBER_EXCLUDED`. When a member re-engages, a `QualityReviewer` revokes the approved request with an optional `reason`: the request moves to `REVOKED`, every gap the original approval had excluded reverts from `EXCLUDED` to `OPEN`, the member's `open_gap_count` is incremented back, the `PROVISIONAL` denominator is restored, and each restored gap's `priority_score` is recomputed. Exclusion requests are listable per member or flat, with `status`, `member_id`, and `measure_id` filters.

Disenrollment is the blunt instrument. An administrator disenrolls a member with an optional `reason`; the member's `enrollment_status` becomes `DISENROLLED`, every care gap of that member sitting in `OPEN`, `OUTREACH_IN_PROGRESS`, `AWAITING_APPOINTMENT`, `PENDING_EVIDENCE`, or `REOPENED` is forced to `EXPIRED`, and the member's `open_gap_count` is zeroed.

### 3.8. Reconciliation, Reopening, Expiry, and Performance Reporting

The claims feed sometimes contradicts the registry: a gap closed on claims evidence turns out not to have closed at all. Reopening is reserved for the `DataReconciliationBot` and accepts an optional `reason`. Only a gap that is `CLOSED` and whose `closure_source` is `CLAIMS_FEED` is eligible — reconciliation may not disturb evidence- or appointment-derived closures, and an ineligible state fails with `ERR_INVALID_STATE`. The reconciliation window must still be open: the clock must not have reached the gap's `due_date` plus the measure's `reporting_lag_days`, otherwise the reopen fails with `ERR_RECONCILIATION_WINDOW_CLOSED`. A successful reopen sets the gap to `REOPENED`, clears its `closure_source` to null, increments the member's `open_gap_count` by one, decrements the owning manager's `closed_gap_count_period` by one, recomputes every `PROJECTED` payout for the current period, and decrements the `PROVISIONAL` report's `numerator_count` by one with `closure_rate_bps` recomputed. A reopened gap is not worked immediately: when the registry clock reaches the gap's `next_eligible_attempt_at`, the system automatically re-triages it from `REOPENED` back to `OPEN`, recomputing its `priority_score` with the 12-point reopen bonus now in force.

Expiry is the mirror sweep. Whenever the registry clock is at or past a gap's `due_date` plus the measure's `reporting_lag_days` and the gap still sits in any of `OPEN`, `OUTREACH_IN_PROGRESS`, `AWAITING_APPOINTMENT`, `PENDING_EVIDENCE`, or `REOPENED`, the system moves it to the terminal `EXPIRED` status and decrements the member's `open_gap_count` by one.

Performance reporting turns gap activity into measure rates. An administrator generates a report for a measure by supplying a `period_key` in `YYYY-MM` form; the report is created in the `PROVISIONAL` variant with `denominator_count`, `numerator_count`, and `closure_rate_bps` computed and its `registry_id` denormalized from the measure. The denominator counts members matching the panel's cohort who are `ENROLLED` at evaluation time and have no approved exclusion covering the measure whose `[effective_from, effective_until)` window overlaps the reporting period. The numerator counts denominator members with at least one care gap for the measure that transitioned to `CLOSED` inside the period window. The closure rate is the numerator multiplied by 10000 and divided by the denominator, rounded half up to an integer number of basis points; when the denominator is zero the rate is null rather than zero. Both counts are plain integers with no rounding.

The two variants differ in how they treat the reconciliation tail. The `PROVISIONAL` variant — the only one that exists while the clock has not yet reached the period end plus `reporting_lag_days` — includes gaps closed via `CLAIMS_FEED` that have not yet been reconciliation-checked, and its denominator uses the live exclusion list. Finalizing a report requires the clock to have reached the period end plus the measure's `reporting_lag_days`; finalizing earlier fails with `ERR_RECONCILIATION_WINDOW_OPEN`. Finalization flips the `variant` to `FINAL`, stamps `reconciled_at` with the registry's `current_business_date`, and recomputes numerator and denominator under final rules: claims-feed closures that were later reopened — gaps whose current status is `REOPENED` or `OPEN` — are excluded from the numerator even when their original closure fell inside the period, and the denominator freezes the set of exclusions approved as of the period end plus lag. Reports are listable per measure or flat, with `period_key`, `variant`, `measure_id`, and `registry_id` filters.

### 3.9. Panel Manager Workload and Incentive Payouts

Workload tracking rows give each panel manager a per-period scorecard. An administrator creates one with the manager's `panel_manager_id` and a `period_key` in `YYYY-MM` form; `assigned_member_count`, `closed_gap_count_period`, and `utilization_ratio` are initialized at creation. Thereafter `assigned_member_count` is maintained as the sum of `member_count` across that manager's panels in `ACTIVE` status, and `closed_gap_count_period` counts care-gap transitions into `CLOSED` during the current program month, moving up on each closure and back down on each reopen as §3.6 and §3.8 describe. The `utilization_ratio` is the assigned member count divided by the workload target of 250 members, rounded half up to four decimal places. Workloads are listable within a registry with `panel_manager_id` and `period_key` filters.

Incentive payouts hang off the workload row via their `workload_id`. A payout's `panel_manager_id` and `period_key` are denormalized from its parent workload, and its status vocabulary is `PROJECTED`, `APPROVED`, `PAID`, and `VOID`. An administrator computes or refreshes the `PROJECTED` payout for the workload's period, and later approves it, moving `PROJECTED` to `APPROVED`.

The payout formula pins its rounding order. The manager's `utilization_ratio` selects a `tier_multiplier_bps`: below 0.80 utilization the multiplier is 10000 basis points; at least 0.80 but below 1.00 it is 12000; at 1.00 or above it is 15000. The per-gap line is the base rate of 4500 cents per closed gap, multiplied by the tier multiplier and divided by 10000, rounded half up to whole cents — and this rounding happens per gap, before any multiplication by volume. The `base_amount_cents` is that per-gap line multiplied by `closed_gap_count_period`. A `quality_bonus_cents` of 50000 cents is added when the measure's `PROVISIONAL` closure rate reaches at least 7000 basis points (70 percent), and is zero otherwise. The `total_payout_cents` is the base amount plus the quality bonus. Payouts are listable per workload, and every recompute triggered by the closure and reopen cascades of §3.6 and §3.8 applies this same pinned formula to the `PROJECTED` rows of the current period.

## 4. Endpoint Definitions

All endpoints are mounted under `/population-health`. Creating a new resource returns HTTP 201 with the created resource in `data`; operations that modify an existing resource, and all reads, return HTTP 200. Every request requires the `X-User-ID` and `X-User-Role` headers described in §2.1, and the response envelope of §2.2 applies uniformly.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /population-health/_clock/set_current_utc | Advance a registry's logical clock; may trigger system transitions | ProgramAdministrator |
| POST | /population-health/registries | Create a population registry | ProgramAdministrator |
| GET | /population-health/registries | List registries | ProgramAdministrator, PanelManager, QualityReviewer, TransportationCoordinator, DataReconciliationBot |
| GET | /population-health/registries/{id} | Get a registry | ProgramAdministrator, PanelManager, QualityReviewer, TransportationCoordinator, DataReconciliationBot |
| POST | /population-health/registries/{id}/measure-definitions | Create a measure definition (DRAFT) | ProgramAdministrator |
| POST | /population-health/measure-definitions/{id}/publish | Publish a measure (DRAFT → PUBLISHED) | ProgramAdministrator |
| GET | /population-health/registries/{id}/measure-definitions | List measures in a registry | ProgramAdministrator, PanelManager, QualityReviewer, DataReconciliationBot |
| GET | /population-health/measure-definitions/{id} | Get a measure | ProgramAdministrator, PanelManager, QualityReviewer, DataReconciliationBot |
| POST | /population-health/registries/{id}/cohort-definitions | Create a cohort definition (DRAFT) | ProgramAdministrator |
| POST | /population-health/cohort-definitions/{id}/activate | Activate a cohort (DRAFT → ACTIVE) | ProgramAdministrator |
| GET | /population-health/registries/{id}/cohort-definitions | List cohorts in a registry | ProgramAdministrator, PanelManager, QualityReviewer, DataReconciliationBot |
| POST | /population-health/registries/{id}/members | Register a member | ProgramAdministrator |
| GET | /population-health/registries/{id}/members | List members (filters: risk_tier, enrollment_status) | ProgramAdministrator, PanelManager, QualityReviewer, TransportationCoordinator, DataReconciliationBot |
| GET | /population-health/members/{id} | Get a member | ProgramAdministrator, PanelManager, QualityReviewer, TransportationCoordinator, DataReconciliationBot |
| POST | /population-health/members/{id}/disenroll | Disenroll a member; open gaps expire | ProgramAdministrator |
| POST | /population-health/registries/{id}/registry-panels | Create a panel (BUILDING) | ProgramAdministrator |
| POST | /population-health/registry-panels/{id}/activate | Activate a panel and materialize care gaps | ProgramAdministrator |
| POST | /population-health/registry-panels/{id}/rebuild | Rebuild a panel (requires expected_panel_version) | ProgramAdministrator |
| POST | /population-health/registry-panels/{id}/finalize-rebuild | Finalize a rebuild (REBUILDING → ACTIVE) | ProgramAdministrator |
| POST | /population-health/registry-panels/{id}/retire | Retire a panel | ProgramAdministrator |
| GET | /population-health/registries/{id}/registry-panels | List panels in a registry (filter: panel_manager_id) | ProgramAdministrator, PanelManager, QualityReviewer, DataReconciliationBot |
| GET | /population-health/registry-panels/{id} | Get a panel | ProgramAdministrator, PanelManager, QualityReviewer, DataReconciliationBot |
| GET | /population-health/registry-panels/{id}/care-gaps | List care gaps under a panel (filters: status, priority_band) | ProgramAdministrator, PanelManager, QualityReviewer, DataReconciliationBot |
| GET | /population-health/care-gaps/{id} | Get a care gap | ProgramAdministrator, PanelManager, QualityReviewer, DataReconciliationBot |
| GET | /population-health/members/{id}/care-gaps | List a member's care gaps (filter: status) | ProgramAdministrator, PanelManager, QualityReviewer, DataReconciliationBot |
| POST | /population-health/care-gaps/{id}/reopen | Reopen a claims-feed-closed gap | DataReconciliationBot |
| POST | /population-health/registries/{id}/outreach-campaigns | Create a campaign (DRAFT) | ProgramAdministrator |
| POST | /population-health/outreach-campaigns/{id}/schedule | Schedule a campaign | ProgramAdministrator |
| POST | /population-health/outreach-campaigns/{id}/launch | Launch a campaign | ProgramAdministrator |
| POST | /population-health/outreach-campaigns/{id}/pause | Pause a campaign | ProgramAdministrator |
| POST | /population-health/outreach-campaigns/{id}/resume | Resume a campaign | ProgramAdministrator |
| POST | /population-health/outreach-campaigns/{id}/complete | Complete a campaign | ProgramAdministrator |
| POST | /population-health/outreach-campaigns/{id}/cancel | Cancel a campaign | ProgramAdministrator |
| GET | /population-health/registries/{id}/outreach-campaigns | List campaigns in a registry (filter: status) | ProgramAdministrator, PanelManager, QualityReviewer, DataReconciliationBot |
| GET | /population-health/outreach-campaigns/{id} | Get a campaign | ProgramAdministrator, PanelManager, QualityReviewer, DataReconciliationBot |
| POST | /population-health/care-gaps/{id}/outreach-attempts | Record an outreach attempt (requires expected_care_gap_version) | PanelManager |
| GET | /population-health/care-gaps/{id}/outreach-attempts | List attempts on a care gap | ProgramAdministrator, PanelManager, QualityReviewer, DataReconciliationBot |
| POST | /population-health/care-gaps/{id}/appointments | Schedule an appointment against a care gap | PanelManager |
| GET | /population-health/care-gaps/{id}/appointments | List appointments for a care gap (filter: status) | ProgramAdministrator, PanelManager, QualityReviewer, TransportationCoordinator, DataReconciliationBot |
| GET | /population-health/appointments/{id} | Get an appointment | ProgramAdministrator, PanelManager, QualityReviewer, TransportationCoordinator, DataReconciliationBot |
| POST | /population-health/appointments/{id}/confirm | Confirm an appointment | PanelManager |
| POST | /population-health/appointments/{id}/complete | Complete an appointment; auto-creates closure evidence | PanelManager |
| POST | /population-health/appointments/{id}/mark-no-show | Mark an appointment as no-show | PanelManager |
| POST | /population-health/appointments/{id}/cancel | Cancel an appointment | PanelManager |
| POST | /population-health/appointments/{id}/reschedule | Reschedule an appointment (cyclic) | PanelManager |
| POST | /population-health/appointments/{id}/transportation-assists | Request a transportation assist | PanelManager, TransportationCoordinator |
| POST | /population-health/transportation-assists/{id}/arrange | Mark an assist arranged | TransportationCoordinator |
| POST | /population-health/transportation-assists/{id}/complete | Mark an assist complete | TransportationCoordinator |
| POST | /population-health/transportation-assists/{id}/cancel | Cancel an assist | TransportationCoordinator |
| GET | /population-health/appointments/{id}/transportation-assists | List assists for an appointment | ProgramAdministrator, PanelManager, TransportationCoordinator, QualityReviewer |
| GET | /population-health/transportation-assists/{id} | Get an assist | ProgramAdministrator, PanelManager, TransportationCoordinator, QualityReviewer |
| POST | /population-health/care-gaps/{id}/gap-closure-evidence | Submit closure evidence | PanelManager, QualityReviewer |
| POST | /population-health/gap-closure-evidence/{id}/approve | Approve evidence (segregation of duties) | QualityReviewer |
| POST | /population-health/gap-closure-evidence/{id}/reject | Reject evidence (segregation of duties) | QualityReviewer |
| GET | /population-health/care-gaps/{id}/gap-closure-evidence | List evidence for a care gap (filter: status) | ProgramAdministrator, PanelManager, QualityReviewer, DataReconciliationBot |
| GET | /population-health/gap-closure-evidence/{id} | Get an evidence record | ProgramAdministrator, PanelManager, QualityReviewer, DataReconciliationBot |
| POST | /population-health/members/{id}/exclusion-requests | Submit an exclusion request | PanelManager, ProgramAdministrator |
| POST | /population-health/exclusion-requests/{id}/start-review | Move an exclusion to UNDER_REVIEW | QualityReviewer |
| POST | /population-health/exclusion-requests/{id}/approve | Approve an exclusion (segregation of duties) | QualityReviewer |
| POST | /population-health/exclusion-requests/{id}/deny | Deny an exclusion (segregation of duties) | QualityReviewer |
| POST | /population-health/exclusion-requests/{id}/revoke | Revoke an approved exclusion | QualityReviewer |
| GET | /population-health/members/{id}/exclusion-requests | List a member's exclusion requests (filter: status) | ProgramAdministrator, PanelManager, QualityReviewer |
| GET | /population-health/exclusion-requests/{id} | Get an exclusion request | ProgramAdministrator, PanelManager, QualityReviewer |
| POST | /population-health/registries/{id}/panel-manager-workloads | Create a workload tracking row | ProgramAdministrator |
| GET | /population-health/registries/{id}/panel-manager-workloads | List workloads (filters: panel_manager_id, period_key) | ProgramAdministrator, PanelManager |
| GET | /population-health/panel-manager-workloads/{id} | Get a workload row | ProgramAdministrator, PanelManager |
| GET | /population-health/panel-manager-workloads/{id}/incentive-payouts | List payouts for a workload row | ProgramAdministrator, PanelManager |
| POST | /population-health/panel-manager-workloads/{id}/incentive-payouts/projection | Compute or refresh the PROJECTED payout | ProgramAdministrator |
| POST | /population-health/incentive-payouts/{id}/approve | Approve a payout (PROJECTED → APPROVED) | ProgramAdministrator |
| GET | /population-health/incentive-payouts/{id} | Get a payout | ProgramAdministrator, PanelManager |
| POST | /population-health/measure-definitions/{id}/measure-performance-reports | Generate a PROVISIONAL report for a period | ProgramAdministrator |
| POST | /population-health/measure-performance-reports/{id}/finalize | Finalize a report after the reconciliation lag | ProgramAdministrator |
| GET | /population-health/measure-definitions/{id}/measure-performance-reports | List reports for a measure (filters: period_key, variant) | ProgramAdministrator, PanelManager, QualityReviewer, DataReconciliationBot |
| GET | /population-health/measure-performance-reports/{id} | Get a report | ProgramAdministrator, PanelManager, QualityReviewer, DataReconciliationBot |
| GET | /population-health/registry-panels | Flat filtered list of panels (filters: cohort_id, measure_id, panel_manager_id) | ProgramAdministrator, PanelManager, QualityReviewer, DataReconciliationBot |
| GET | /population-health/care-gaps | Flat filtered list of care gaps (filters: panel_id, member_id, measure_id, status, priority_band) | ProgramAdministrator, PanelManager, QualityReviewer, DataReconciliationBot |
| GET | /population-health/outreach-campaigns | Flat filtered list of campaigns (filters: panel_id, measure_id, status) | ProgramAdministrator, PanelManager, QualityReviewer, DataReconciliationBot |
| GET | /population-health/outreach-attempts | Flat filtered list of outreach attempts (filters: care_gap_id, campaign_id, member_id) | ProgramAdministrator, PanelManager, QualityReviewer, DataReconciliationBot |
| GET | /population-health/outreach-attempts/{id} | Get a single outreach attempt | ProgramAdministrator, PanelManager, QualityReviewer, DataReconciliationBot |
| GET | /population-health/appointments | Flat filtered list of appointments (filters: care_gap_id, member_id, provider_id, status) | ProgramAdministrator, PanelManager, QualityReviewer, TransportationCoordinator, DataReconciliationBot |
| GET | /population-health/transportation-assists | Flat filtered list of transportation assists (filters: appointment_id, member_id, status) | ProgramAdministrator, PanelManager, TransportationCoordinator, QualityReviewer |
| GET | /population-health/gap-closure-evidence | Flat filtered list of gap-closure evidence (filters: care_gap_id, member_id, status) | ProgramAdministrator, PanelManager, QualityReviewer, DataReconciliationBot |
| GET | /population-health/exclusion-requests | Flat filtered list of exclusion requests (filters: member_id, measure_id, status) | ProgramAdministrator, PanelManager, QualityReviewer |
| GET | /population-health/measure-performance-reports | Flat filtered list of reports (filters: measure_id, registry_id, period_key, variant) | ProgramAdministrator, PanelManager, QualityReviewer, DataReconciliationBot |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_CAMPAIGN_NOT_ACTIVE | 409 |
| ERR_CAMPAIGN_NOT_YET_OPEN | 409 |
| ERR_CAMPAIGN_WINDOW_PAST | 409 |
| ERR_INVALID_CAMPAIGN_WINDOW | 400 |
| ERR_CAMPAIGN_WINDOW_VIOLATION | 409 |
| ERR_ATTEMPT_TOO_EARLY | 409 |
| ERR_ATTEMPT_CAP_REACHED | 409 |
| ERR_CHANNEL_CONSENT_MISSING | 403 |
| ERR_MEMBER_EXCLUDED | 409 |
| ERR_APPOINTMENT_ALREADY_ACTIVE | 409 |
| ERR_PROVIDER_SLOT_FULL | 409 |
| ERR_INVALID_SLOT | 400 |
| ERR_CANNOT_MARK_FUTURE_APPOINTMENT | 409 |
| ERR_APPOINTMENT_NOT_CONFIRMED | 409 |
| ERR_TRANSPORT_NOT_ARRANGED | 409 |
| ERR_INVALID_COST | 400 |
| ERR_EVIDENCE_OUT_OF_WINDOW | 409 |
| ERR_SOD_VIOLATION | 403 |
| ERR_INSUFFICIENT_JUSTIFICATION | 400 |
| ERR_EXCLUSION_BLOCKED_BY_APPOINTMENT | 409 |
| ERR_RECONCILIATION_WINDOW_OPEN | 409 |
| ERR_RECONCILIATION_WINDOW_CLOSED | 409 |
| ERR_PANEL_NOT_ACTIVE | 409 |

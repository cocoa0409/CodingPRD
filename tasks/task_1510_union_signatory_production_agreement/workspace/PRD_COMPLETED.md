# Union Signatory Production Agreement API — Product Requirements Document

## 1. Introduction

Producers who sign collective bargaining agreements with entertainment unions take on a durable set of obligations: they post wage-and-hour security bonds before a frame is shot, staff each department to agreement minimums, honor meal and turnaround rules on every work day, report pension and health contributions each period, answer grievances through a structured negotiation and arbitration ladder, and stand ready for fund audits that can reach back into accepted reports and forfeit the bond. This document specifies an API that makes that entire compliance surface a system of record for signatory producers working under SAG-AFTRA/IATSE-style agreements.

The API governs the full arc from applicant to closed production. A company registers, applies for signatory status, and — once approved — registers productions under budget-appropriate agreement tiers. Each production carries a compliance posture derived from live signals (open grievances, bond health, unpaid audit findings, active strikes) that gates what the producer may do next: a restricted production cannot expand its crew, and a frozen one stops almost all work-logging and reporting. Two actors on opposite sides of the table (producer representatives and union representatives) plus fund trustees and a neutral arbitrator share the same deterministic logical clock, so filing deadlines, suspension windows, and reinstatement cascades behave identically for every client. Segregation of duties is enforced where the real-world process demands it: the union staffer who intakes a grievance may not be the one who proposes its settlement, and the trustee who opens an audit may not be the one who closes it.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes exactly five roles: `ProducerRep`, `UnionRep`, `FundTrustee`, `Arbitrator`, and `PlatformAdmin`. A request missing either header, or presenting an `X-User-Role` value that is not one of these five, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not on the target endpoint's authorized list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Role identity works in two distinct ways. When `X-User-Role` is `ProducerRep`, `X-User-ID` is the `id` of the acting ProducerCompany — the `id` returned by company registration becomes the caller's `X-User-ID` for every subsequent call — and ownership checks on any resource that belongs to a company (directly, or via the `production_id` chain from a production down to its bond, crew assignments, work day logs, grievances, contribution reports, audits, and force majeure events) compare the resource's owning company `id` to `X-User-ID`. A `ProducerRep` whose `X-User-ID` does not match the company that owns the target resource is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403); this ownership check applies to every `ProducerRep` endpoint except company registration itself. When `X-User-Role` is `UnionRep`, `FundTrustee`, `Arbitrator`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity: the server records it where the workflow demands an audit trail — `filed_by_user_id` and `intake_user_id` on a grievance, `opened_by_user_id` and `closed_by_user_id` on an audit — but never compares it to any entity's `id`.

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

List endpoints accept two query parameters. `limit` sets the maximum number of items returned: it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped and defaults to 0. A `limit` or `offset` that does not parse as an integer, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_VALIDATION` (HTTP 400); these checks run when the list response is assembled, after the target resource has resolved and any ownership check has passed. Unless stated otherwise, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by `id` ascending. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope: `total_count` is the full count of matching resources before pagination, and `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`.

### 2.4. Common Resource Properties and Mutation Bookkeeping

Every resource in the system — companies, applications, productions, bonds, crew assignments, work day logs, grievances, contribution reports, audits, and force majeure events — carries a standard quartet of system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created. `updated_at` is the same format and is refreshed on every mutation. `version` is an integer that starts at 1 on creation and increments by exactly one on every mutation of the resource — and every state transition described anywhere in §3 is a mutation, so each transition bumps the entity's `version` by one and refreshes `updated_at` without exception. No transition ever leaves `version` unchanged. Two system-derived field updates are exempt from the version rule: recomputation of a production's persisted `compliance_posture` (§2.8) and recomputation of a bond's `amount_required_cents` during a tier-upgrade cascade (§3.3) update the stored field in place and do not by themselves increment `version` or refresh `updated_at`. Each entity additionally carries its own system-managed lifecycle `status` field, whose enumerated values are defined alongside that entity's workflow in §3. Calendar-date payload fields (`work_date`, `incident_date`, `start_date`, `end_date`) must be ISO 8601 calendar dates in strict `YYYY-MM-DD` form; anything else is `ERR_VALIDATION`.

Every identifier the client supplies must exist. Path `id` parameters and foreign-key references in request bodies — `producer_company_id`, `production_id`, `crew_assignment_id`, and each element of `work_day_log_ids` — are resolved before business rules run; a reference to a non-existent resource is rejected with `ERR_RESOURCE_NOT_FOUND` (HTTP 404). Where a request path chains one resource beneath another, identifiers are validated strictly left to right, and the first identifier that does not resolve produces the 404.

### 2.5. The Logical Clock

All time-dependent behavior in the system reads a single server-side logical clock — never the host's wall clock. The clock's startup default, before any client call, is exactly `2026-08-01T00:00:00Z`, and the server must not silently fall back to wall-clock time at any point. A `PlatformAdmin` advances the clock through a test-driving capability that accepts a `to_iso8601` instant — a value without an explicit offset is interpreted as UTC — and sets the logical clock to it. The grievance filing window, the `signatory_since` stamp on a newly signatory company, and the `lifted_date` stamp on a lifted force majeure event all read this clock. Entity `created_at`/`updated_at` bookkeeping and the response envelope's `api_request_timestamp` are formatted from the host clock and are not logical-clock reads.

### 2.6. Money, Precision, and Rounding

All monetary quantities are integer cents; there are no fractional cents and no floating-point money anywhere in the API. Wherever a calculation prescribes rounding, the method is round half up to a whole cent. Where a calculation pins an evaluation order — rounding a per-unit penalty before multiplying, flooring and rounding each audit period before summing, or multiplying a wage base by a rate numerator before dividing by 100 — that order is contractual, and alternative orderings that yield different cent values are non-conformant.

### 2.7. Agreement Tiers, Budget Caps, and the Bond Schedule

Four agreement tiers exist, in ascending order: `ULTRA_LOW_BUDGET`, then `MODIFIED_LOW_BUDGET`, then `LOW_BUDGET`, then `BASIC`. Each tier below `BASIC` caps the production budget it can cover: `ULTRA_LOW_BUDGET` covers budgets up to 30,000,000 cents (three hundred thousand dollars), `MODIFIED_LOW_BUDGET` up to 75,000,000 cents, and `LOW_BUDGET` up to 250,000,000 cents; `BASIC` is uncapped. The cap boundary is inclusive — a budget exactly equal to a tier's cap is covered by that tier.

Each production must post a wage-and-hour security bond whose required amount is a flat per-tier figure: 2,500,000 cents for `ULTRA_LOW_BUDGET`, 5,000,000 cents for `MODIFIED_LOW_BUDGET`, 10,000,000 cents for `LOW_BUDGET`, and 25,000,000 cents for `BASIC`. A tier upgrade strictly increases the bond requirement. Bond sufficiency checks compare integer cents exactly.

### 2.8. The Compliance Posture

Every production carries a persisted, system-computed `compliance_posture` that is always one of `CLEAR`, `RESTRICTED`, or `FROZEN`. It is recomputed and re-persisted whenever any of its inputs change: a force majeure event is declared or lifted; a grievance is created or reaches `CLOSED`; the production's bond transitions among `PENDING`, `POSTED`, `UNDERFUNDED`, and `FORFEITED`; or an audit of the production transitions or receives a payment.

The derivation is evaluated in a pinned priority order — `FROZEN` first, then `RESTRICTED`, then `CLEAR`. If any force majeure event of the production has status `ACTIVE`, the posture is `FROZEN`. Otherwise, the posture is `RESTRICTED` when at least one of three conditions holds: the count of the production's grievances in `FILED`, `INVESTIGATING`, `PROPOSED_SETTLEMENT`, or `ESCALATED` status reaches 2; the production's bond is `UNDERFUNDED` or `FORFEITED`; or any audit of the production is `FINDINGS_ISSUED` with `assessment_paid_cents` still below `assessment_cents`. If none of these holds, the posture is `CLEAR`. The grievance-count threshold is inclusive: exactly 2 open grievances already restrict the production.

The posture gates operations. Hiring crew and starting production both require `CLEAR`: a `RESTRICTED` posture rejects them with `ERR_POSTURE_RESTRICTED` (HTTP 409) and a `FROZEN` posture with `ERR_POSTURE_FROZEN` (HTTP 409). Creating, submitting, or voiding work day logs, creating or submitting contribution reports, and transitioning crew assignments require only that the posture not be `FROZEN`, and are rejected with `ERR_POSTURE_FROZEN` while it is. Grievance filing is deliberately not posture-gated — grievances may be filed during a strike.

### 2.9. Optimistic Concurrency Control

Exactly two write operations are guarded by optimistic concurrency. Applying a budget revision to a production requires the request to carry `expected_production_version` holding the production's `version` as the client last observed it. Submitting a settlement proposal on a grievance requires `expected_grievance_version` holding the grievance's `version` as last observed. In both cases the field is non-optional: if the supplied value does not equal the entity's current `version` — because another writer has advanced the entity since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting changes it has not observed. No other endpoint accepts a version field.

### 2.10. Validation Pipeline and Ordering

When several checks could reject the same request, the server evaluates them in a fixed order so that the surfaced error is deterministic. Authentication comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_UNAUTHORIZED_ROLE`). Endpoints that take a request body then validate it — malformed payloads, fields not declared for the endpoint, missing required fields, undeclared enum members, and out-of-range integers are `ERR_VALIDATION` (HTTP 400); endpoints whose definition names no request fields ignore the body entirely. References then resolve and `ProducerRep` ownership is applied: the reference that determines ownership — the path `id`, or the body reference whose chain leads to the owning company — resolves first (`ERR_RESOURCE_NOT_FOUND`), then ownership is checked (`ERR_NOT_RESOURCE_OWNER`), and any remaining body references (the elements of `work_day_log_ids`, a grievance filing's `crew_assignment_id`) resolve after ownership. The signatory-application action endpoints (`submit`, `request-info`, `provide-info`, `decide`) are the one exception: they resolve the application and check ownership before validating the body. The optimistic-concurrency check (`ERR_STALE_VERSION`) comes after all of these.

State gates come after those, in this sequence: production-state gating (`ERR_PRODUCTION_STATE`); the frozen-posture gate (`ERR_POSTURE_FROZEN`), which fires before the restricted-posture gate (`ERR_POSTURE_RESTRICTED`); then the from-state gates for applications (`ERR_APPLICATION_STATE`), bonds (`ERR_BOND_STATE`), crew assignments (`ERR_ASSIGNMENT_STATE`), work day logs (`ERR_WORKLOG_STATE`), grievances (`ERR_GRIEVANCE_STATE`), contribution reports (`ERR_REPORT_STATE`), audits (`ERR_AUDIT_STATE`), and force majeure events (`ERR_FM_STATE`); and the signatory precondition on production creation (`ERR_COMPANY_NOT_SIGNATORY`).

Business rules run last, in this fixed sequence: minimum staffing (`ERR_MIN_STAFF_UNMET`); the grievance filing window (`ERR_FILING_WINDOW_EXPIRED`); cross-production references (`ERR_CROSS_PRODUCTION_REFERENCE`); already-reported work logs (`ERR_LOG_ALREADY_REPORTED`); duplicate active crew assignment (`ERR_DUPLICATE_ACTIVE_ASSIGNMENT`); duplicate work day log (`ERR_DUPLICATE_WORK_LOG`); duplicate report period (`ERR_DUPLICATE_REPORT_PERIOD`); force majeure interval overlap (`ERR_FM_OVERLAP`); segregation of duties (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403); review-round exhaustion (`ERR_REVIEW_ROUNDS_EXHAUSTED`); empty report (`ERR_EMPTY_REPORT`); work-log time sanity (`ERR_INVALID_WORKLOG_TIMES`); tier coverage (`ERR_TIER_CAP_EXCEEDED`); bond sufficiency (`ERR_BOND_AMOUNT_INSUFFICIENT`); overpayment (`ERR_OVERPAYMENT`); and refund limits (`ERR_REFUND_EXCEEDS_PAID`).

## 3. Business Logic & Workflows

### 3.1. Becoming a Signatory: Companies and Applications

A `ProducerRep` onboards by registering a production company with its `legal_name` and `fein` — the Federal Employer Identification Number; `fein` is recorded as supplied and uniqueness across companies is not enforced. The company is created with status `PENDING` and `version` 1, and the `id` in the response becomes the caller's `X-User-ID` for all subsequent `ProducerRep` calls. While `PENDING`, the company's `signatory_since` is null.

The same representative then drafts a signatory application, supplying `producer_company_id`, a `requested_agreement_scope` of `THEATRICAL`, `TELEVISION`, or `NEW_MEDIA`, and an `estimated_slate_budget_cents` (an integer no less than zero) covering the company's planned slate. The application starts in `DRAFT`. Submitting it — allowed whether the company is `PENDING`, `SIGNATORY`, or `SUSPENDED` — moves it to `UNDER_REVIEW`; submitting from any other state is rejected with `ERR_APPLICATION_STATE` (HTTP 409).

Review is a bounded negotiation loop. A `UnionRep` may push the application from `UNDER_REVIEW` to `INFO_REQUESTED`; the request may carry an optional `info_request_note`, which is validated as a string when present but not persisted on the application. Each such request consumes one of at most 3 review rounds, recorded in `review_rounds`, and a request made when `review_rounds` has already reached 3 is rejected with `ERR_REVIEW_ROUNDS_EXHAUSTED` (HTTP 422). The producer answers with provide-info — whose `info_response` is likewise optional, validated as a string when present, and not persisted — returning the application from `INFO_REQUESTED` to `UNDER_REVIEW` for another look. Request-info and decide are only valid from `UNDER_REVIEW`, and provide-info only from `INFO_REQUESTED`; any other from-state is `ERR_APPLICATION_STATE`.

The loop ends when a `UnionRep` decides the application with a `decision` of `APPROVE` or `DENY`. Approval moves the application to `APPROVED`; if the company is still `PENDING`, the company transitions to `SIGNATORY` and `signatory_since` is stamped from the logical clock, while a company already `SIGNATORY` or `SUSPENDED` is left as-is. Denial requires a `denial_reason` in the payload — its absence is `ERR_VALIDATION` — records the reason on the application, and moves it to `DENIED`; a `denial_reason` supplied with `APPROVE` is accepted but not recorded. `APPROVED` and `DENIED` are terminal.

### 3.2. Registering a Production: Tiers, Bonds, and Posting

Only a `SIGNATORY` company may register a production: the `ProducerRep` supplies `producer_company_id`, `title`, `agreement_tier`, and `budget_cents` — the last an integer greater than zero (`ERR_VALIDATION` otherwise) — and if the named company is not `SIGNATORY` the request fails with `ERR_COMPANY_NOT_SIGNATORY` (HTTP 409). The chosen tier must cover the budget per the schedule of §2.7 — a budget above the selected tier's cap is rejected with `ERR_TIER_CAP_EXCEEDED` (HTTP 422), while a budget exactly equal to the cap passes. A new production starts in `REGISTERED` with `compliance_posture` `CLEAR` and `pre_suspension_status` null.

Creation has one automatic side effect: exactly one bond is created for the production in status `PENDING`, its `amount_required_cents` set from the per-tier bond schedule keyed on the production's current tier. The bond keeps a running ledger — `total_posted_cents`, `total_released_cents`, and `total_forfeited_cents` all start at zero — and its `amount_held_cents` is always the posted total minus the released total minus the forfeited total.

Posting the bond is the gate to staffing. A `ProducerRep` posts an `amount_cents` that must be at least `amount_required_cents`; anything less is rejected with `ERR_BOND_AMOUNT_INSUFFICIENT` (HTTP 422). On success the posted total increases by `amount_cents`, the held amount is recomputed, the bond moves from `PENDING` to `POSTED`, the production moves from `REGISTERED` to `STAFFING`, and the production's posture is recomputed. Posting on a bond in any state other than `PENDING` or `FORFEITED` is `ERR_BOND_STATE`.

### 3.3. Budget Revisions and the Tier-Upgrade Cascade

Budgets move. While a production is `REGISTERED`, `STAFFING`, `IN_PRODUCTION`, `SUSPENDED`, or `WRAPPED` — but never `CLOSED`, which rejects with `ERR_PRODUCTION_STATE` — a `ProducerRep` may apply a budget revision carrying `new_budget_cents` and `expected_production_version`. The new budget must be greater than zero (`ERR_VALIDATION` otherwise), and the version must match the production's current `version` or the revision is rejected with `ERR_STALE_VERSION` (HTTP 412) per §2.9: a client whose view predates another writer's revision — one that may legitimately have upgraded the tier and cascaded into bond and posture — must not overwrite it blindly.

A revision updates `budget_cents` and then re-evaluates the tier. If the current tier's cap covers the new budget, the tier is unchanged; a lower budget never downgrades the tier. Otherwise the tier upgrades to the smallest tier, in the declaration order of §2.7, whose cap covers the new budget. An upgrade cascades: the bond's `amount_required_cents` is recomputed from the new tier's flat requirement, and if the bond's `amount_held_cents` now falls short of the new requirement, the bond transitions from `POSTED` to `UNDERFUNDED` on its own — and that bond transition in turn recomputes the production's posture, forcing `RESTRICTED` unless the production is `FROZEN`.

Recovery runs through the top-up. On an `UNDERFUNDED` bond, a `ProducerRep` tops up an `amount_cents` that must be at least the requirement minus the currently held amount; shortfalls are `ERR_BOND_AMOUNT_INSUFFICIENT`. A successful top-up increases the posted total, recomputes the held amount, returns the bond to `POSTED`, and recomputes posture — which may return to `CLEAR` once the underfunding condition lifts. Topping up a bond in any other state is `ERR_BOND_STATE`.

### 3.4. Crew Assignments, Minimum Staffing, and the Start of Photography

Crew are hired onto productions in `STAFFING` or `IN_PRODUCTION` whose posture is `CLEAR` — there is no workforce expansion while restricted or frozen: a `FROZEN` posture rejects the hire with `ERR_POSTURE_FROZEN` and a `RESTRICTED` posture with `ERR_POSTURE_RESTRICTED`. The `ProducerRep` supplies `production_id`, `crew_member_ref` (an external worker reference), a `department` of `CAMERA`, `GRIP_ELECTRIC`, or `SOUND`, a `classification` of `DIRECTOR_OF_PHOTOGRAPHY`, `CAMERA_OPERATOR`, `GAFFER`, `KEY_GRIP`, `BOOM_OPERATOR`, or `SOUND_MIXER`, and a `daily_rate_cents` that must be greater than zero. At most one assignment per production and `crew_member_ref` may be live — that is, in `HIRED` or `ACTIVE` status — and a duplicate is rejected with `ERR_DUPLICATE_ACTIVE_ASSIGNMENT` (HTTP 409). New assignments start `HIRED`.

Assignments move via a transition request naming a `to_state`. Activation — `HIRED` to `ACTIVE` — requires the production to be `IN_PRODUCTION` (`ERR_PRODUCTION_STATE` otherwise) and its posture not `FROZEN`. Wrapping moves an assignment from `HIRED` or `ACTIVE` to `WRAPPED` while the production is `IN_PRODUCTION`. Termination moves an assignment from `HIRED` or `ACTIVE` to `TERMINATED` whenever the production is not `CLOSED`. Any transition attempted from the terminal states `WRAPPED` or `TERMINATED` is rejected with `ERR_ASSIGNMENT_STATE` (HTTP 409).

Starting photography is the first posture-gated milestone. The production must be `STAFFING` (`ERR_PRODUCTION_STATE` otherwise) and `CLEAR` — restricted yields `ERR_POSTURE_RESTRICTED`, frozen yields `ERR_POSTURE_FROZEN` — and it must meet the per-tier minimum staffing. Counting only assignments in `HIRED` or `ACTIVE` within each department (wrapped and terminated crew do not count), an `ULTRA_LOW_BUDGET` production needs at least one crew member in each of `CAMERA`, `GRIP_ELECTRIC`, and `SOUND`; `MODIFIED_LOW_BUDGET` needs two in `CAMERA`, two in `GRIP_ELECTRIC`, and one in `SOUND`; `LOW_BUDGET` needs three in `CAMERA`, two in `GRIP_ELECTRIC`, and two in `SOUND`; and `BASIC` needs four in `CAMERA`, three in `GRIP_ELECTRIC`, and two in `SOUND`. The boundary is inclusive — a count exactly equal to a department minimum passes — and any department one short fails the whole check with `ERR_MIN_STAFF_UNMET` (HTTP 422). Success moves the production from `STAFFING` to `IN_PRODUCTION`.

### 3.5. Work Day Logs and Penalty Arithmetic

Once a production is `IN_PRODUCTION` and not `FROZEN`, the `ProducerRep` records work days against individual assignments. The referenced assignment must be `ACTIVE` — logging against a `HIRED`, `WRAPPED`, or `TERMINATED` assignment is `ERR_ASSIGNMENT_STATE`. The payload carries `crew_assignment_id`, a `work_date` as an ISO 8601 calendar date, `call_time_minutes` and `wrap_time_minutes` as minutes since midnight, and a `meal_breaks` list whose entries each give `start_minutes` and `end_minutes`. Time sanity is enforced: both times must be at least 0 and strictly below 1440; wrap must be strictly after call; and every meal break must lie within the call-to-wrap span with its start before its end. Violations are rejected with `ERR_INVALID_WORKLOG_TIMES` (HTTP 422). Occupancy is day-point based: at most one non-`VOIDED` log may exist per assignment per `work_date` — a second is `ERR_DUPLICATE_WORK_LOG` (HTTP 409) — while adjacent calendar dates are unaffected. A new log starts `OPEN`, and its penalty fields are computed at creation and recomputed again on submission.

Meal penalties measure how late the first meal breaks. The first meal starts at the earliest `start_minutes` among the listed breaks — or, when `meal_breaks` is empty, is treated as starting at wrap. The delay is that first-meal start minus the sum of the call time and 360 minutes (the six-hour meal window) — `first_meal_start − (call_time + 360)`. A delay of zero or less produces no penalty; otherwise `meal_penalty_units` is the delay divided by 30 minutes, rounded up to the next whole unit. The per-unit penalty is one thirty-second of the assignment's `daily_rate_cents` — a quarter-hour of an eight-hour day rate — and the rounding order is pinned: the per-unit amount is rounded half up to a whole cent first, then multiplied by the units to produce `meal_penalty_cents`. The sum-then-round alternative is rejected.

Turnaround penalties police rest between days. The check looks at the same assignment's non-`VOIDED` log whose `work_date` is exactly the previous calendar day; if none exists, there is no violation. The elapsed rest is the minutes from the previous day's wrap to midnight — 1440 minus the previous wrap — plus this day's call time. `turnaround_violation` is true when that rest is strictly shorter than the production's current tier allowance: 12 hours (720 minutes) for `ULTRA_LOW_BUDGET` and `MODIFIED_LOW_BUDGET`, 10 hours (600 minutes) for `LOW_BUDGET` and `BASIC`. Rest exactly equal to the allowance is not a violation. When violated, `turnaround_penalty_cents` is one eighth of the assignment's `daily_rate_cents`, rounded half up to a whole cent; otherwise it is zero. The log's `penalty_cents` is the sum of the meal and turnaround penalties.

Submitting a log moves it from `OPEN` to `SUBMITTED` (any other from-state is `ERR_WORKLOG_STATE`, HTTP 409), requires the production not be `FROZEN`, and recomputes the penalty fields by the same rules. Voiding corrects the record: a log in `OPEN` or `SUBMITTED` may move to `VOIDED` while the production is not `FROZEN` — and this is allowed even when the log is listed on an `ACCEPTED` contribution report, because the resulting over-report is precisely what audits are built to detect. From the moment it is voided, the log is excluded from all contribution and audit aggregates. `VOIDED` is terminal.

### 3.6. Grievances: Filing, Negotiation, Arbitration, and Settlement

A `UnionRep` files a grievance against a production with `production_id`, an optional `crew_assignment_id`, a `category` of `WORK_RULE`, `PAY`, `CLASSIFICATION`, `SAFETY`, or `OTHER`, the `incident_date`, and a free-text `description`. Filing is not posture-gated — grievances may be filed during a strike. When `crew_assignment_id` is provided it must reference an assignment of the same production; a cross-production reference is `ERR_CROSS_PRODUCTION_REFERENCE` (HTTP 422). The filing representative's header identity is recorded as `filed_by_user_id` for audit, the grievance starts `FILED`, and the production's posture is recomputed because the open-grievance count has changed.

Filing is bounded by a deadline computed in exactly two passes, never iterated further. The first pass sets a provisional deadline 30 days after the `incident_date`. Tolling then collects every force majeure event of the production — `ACTIVE` or `LIFTED` alike — each contributing the interval that runs from its `start_date` up to but not including its effective end, where the effective end is the event's `end_date` if set, else its `lifted_date` if set, else the current logical-clock date. Overlapping intervals are merged into their union and intersected with the span from the incident date to the provisional deadline; the tolling is the whole days of that intersection, counted end-exclusive. The second and final pass sets the deadline to the incident date plus 30 days plus the tolling days. Filing is valid while the current clock date is on or before that deadline — the boundary is inclusive — and a later filing is rejected with `ERR_FILING_WINDOW_EXPIRED` (HTTP 422).

Intake begins the investigation: a `UnionRep` accepts intake on a `FILED` grievance (any other state is `ERR_GRIEVANCE_STATE`, HTTP 409), moving it to `INVESTIGATING` and recording their header identity as `intake_user_id`. Settlement proposals come from a different pair of hands — the proposing `UnionRep`'s `X-User-ID` must differ from `intake_user_id`, or the request is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The proposal carries `proposal_amount_cents` — an integer no less than zero (a negative amount is `ERR_VALIDATION`) — and the OCC field `expected_grievance_version` (a mismatch with the grievance's current `version` is `ERR_STALE_VERSION`). On success the grievance moves from `INVESTIGATING` to `PROPOSED_SETTLEMENT`; if a prior proposal was still `OPEN` it becomes `SUPERSEDED`, the new amount is recorded, and `proposal_status` — which begins as `NONE`, with `proposal_amount_cents` null until the first proposal — becomes `OPEN`.

The producer answers an open proposal with a `decision` while the grievance is `PROPOSED_SETTLEMENT` and the proposal still `OPEN`. An `ACCEPT` marks the proposal `ACCEPTED`, copies its amount into `settlement_agreed_cents`, and moves the grievance to `RESOLVED`; if the agreed amount is zero, the grievance closes immediately — straight to `CLOSED` — and the production's posture is recomputed. A `REJECT` marks the proposal `REJECTED` and sends the grievance back to `INVESTIGATING`, completing one leg of the negotiation cycle.

Either side may escalate: a `UnionRep` or a `ProducerRep` moves the grievance from `INVESTIGATING` or `PROPOSED_SETTLEMENT` to `ESCALATED`, superseding any still-`OPEN` proposal. From `ESCALATED`, an `Arbitrator` decides the matter with an `award_cents` amount (an integer no less than zero) and an optional `decision_notes`, which is validated as a string when present but not persisted on the grievance; deciding from any other state is `ERR_GRIEVANCE_STATE`. The award is recorded as `settlement_agreed_cents`, the grievance moves to `DECIDED`, and an award of zero closes the grievance immediately with a posture recompute. `settlement_agreed_cents` and `settlement_paid_cents` both begin at zero.

Money moves last. Against a grievance in `RESOLVED` or `DECIDED` (payments at any other stage are `ERR_GRIEVANCE_STATE`), a `ProducerRep` pays an `amount_cents` that must be greater than zero and must not push `settlement_paid_cents` past `settlement_agreed_cents` — a breach either way is `ERR_OVERPAYMENT` (HTTP 422). Each payment accumulates into `settlement_paid_cents`, and the payment that brings the paid total exactly level with the agreed amount closes the grievance automatically and recomputes the production's posture as the open-grievance count drops. Refunds are the compensating action: against the same `RESOLVED` or `DECIDED` states, a refund of an `amount_cents` that is greater than zero and no more than the current `settlement_paid_cents` reduces the paid total; anything else is `ERR_REFUND_EXCEEDS_PAID` (HTTP 422).

### 3.7. Contribution Reports and Fund Audits

Contribution reports are the producer's periodic accounting to the pension and health funds. A `ProducerRep` creates one while the production is `IN_PRODUCTION` or `WRAPPED` and not `FROZEN`, supplying `production_id`, a `period_index` of at least 1, and a `work_day_log_ids` list — an explicit, non-empty inclusion set whose elements must each be a string identifier; an empty list is `ERR_EMPTY_REPORT` (HTTP 422). The list is stored verbatim, and an id listed more than once contributes once per occurrence to the dues sums. Every listed log must belong, through its assignment, to the named production (`ERR_CROSS_PRODUCTION_REFERENCE` otherwise), must not be `VOIDED` (a voided log in the set is `ERR_WORKLOG_STATE`), and must not already appear on another `ACCEPTED` report of the production (`ERR_LOG_ALREADY_REPORTED`, HTTP 409). Only one report per production and period may occupy the live statuses — a `DRAFT`, `SUBMITTED`, or `ACCEPTED` report already covering the same `period_index` triggers `ERR_DUPLICATE_REPORT_PERIOD` (HTTP 409). A new report starts `DRAFT`, with `final_gross_wages_cents` and `final_contributions_due_cents` null until submission.

Two variants of the dues calculation exist, pinned to different moments. The provisional variant runs at creation: for each listed log whose status is `OPEN` or `SUBMITTED`, the log's wage contribution is the lesser of its assignment's `daily_rate_cents` and the production tier's daily wage cap — 100,000 cents (one thousand dollars) for `ULTRA_LOW_BUDGET`, 150,000 for `MODIFIED_LOW_BUDGET`, 250,000 for `LOW_BUDGET`, and 500,000 for `BASIC` — using the tier in force at creation. The capped wages sum into `provisional_gross_wages_cents`, and `provisional_contributions_due_cents` multiplies that base by the tier's rate numerator — 17 for `ULTRA_LOW_BUDGET`, 18 for `MODIFIED_LOW_BUDGET`, 19 for `LOW_BUDGET`, 20 for `BASIC` — and divides by 100, with the multiplication performed first and a single round-half-up to whole cents at the end.

Submission locks the final numbers. Moving a report from `DRAFT` to `SUBMITTED` (any other from-state is `ERR_REPORT_STATE`, HTTP 409; the production must not be `FROZEN`) computes the final variant: only listed logs whose status is `SUBMITTED` contribute — logs still `OPEN` contribute zero — and the rate and cap are taken from the production's tier at submit time, so a tier upgrade between creation and submission retroactively changes the rate. The results land in `final_gross_wages_cents` and `final_contributions_due_cents`.

A `FundTrustee` then reviews a `SUBMITTED` report with a `decision`. Acceptance moves it to `ACCEPTED` and marks every listed log as reported, so future reports naming those logs fail with `ERR_LOG_ALREADY_REPORTED`. Rejection requires a `rejection_reason`, records it, moves the report to `REJECTED`, and frees the listed logs for a replacement report; a `rejection_reason` supplied with `ACCEPT` is accepted but not recorded. Both outcomes are terminal.

Audits are the fund's reach-back instrument. A `FundTrustee` opens one with a `production_id` and a non-empty `scope_period_indices` list whose elements are integers no less than 1 (anything else is `ERR_VALIDATION`); the opener's header identity is recorded as `opened_by_user_id`, and the audit starts `OPEN` with `assessment_cents` and `alt_assessment_cents` null until findings are issued and `assessment_paid_cents` at zero. Issuing findings — valid only from `OPEN`, else `ERR_AUDIT_STATE` — computes the assessment. For each `ACCEPTED` report of the production whose `period_index` falls in scope, the expected dues are recomputed with the final-variant formula over the report's `work_day_log_ids`, keeping only logs whose current status is not `VOIDED` and applying the production's current tier rate and cap; the period's shortfall is that expectation minus the report's `final_contributions_due_cents`, and it may be negative when the period was over-reported. The official per-period variant floors each period's shortfall at zero, multiplies by 110 and divides by 100 with round-half-up to whole cents, and sums those per-period amounts into `assessment_cents` — over-reported periods cannot offset under-reported ones. The informational aggregate variant instead nets all shortfalls across periods first, floors the net at zero, and applies the same 110-per-100 penalty with a single rounding, landing in `alt_assessment_cents`. When no `ACCEPTED` report exists in scope, both figures are zero. The audit moves to `FINDINGS_ISSUED`, and the production's posture is recomputed — findings with `assessment_paid_cents` below `assessment_cents` force `RESTRICTED`.

The producer pays an issued assessment in installments: against a `FINDINGS_ISSUED` audit (payments at other stages are `ERR_AUDIT_STATE`), each `amount_cents` must be greater than zero and must not push `assessment_paid_cents` past `assessment_cents` (`ERR_OVERPAYMENT`). Payments accumulate and the posture is recomputed after each, so paying in full may clear a `RESTRICTED` posture.

Closing an audit is segregated from opening it: the acting `FundTrustee`'s `X-User-ID` must differ from `opened_by_user_id`, or the request is `ERR_SEGREGATION_OF_DUTIES`. An audit may close from `OPEN` — in which case the assessment is treated as zero — or from `FINDINGS_ISSUED`; any other state is `ERR_AUDIT_STATE`. The closer's identity is recorded as `closed_by_user_id`. Closing from `FINDINGS_ISSUED` with the assessment not fully paid triggers the forfeit cascade: the production's bond, whether `POSTED` or `UNDERFUNDED`, transitions to `FORFEITED`, the entire held amount moves into `total_forfeited_cents`, `amount_held_cents` is zeroed, the producer company transitions from `SIGNATORY` to `SUSPENDED`, and the production's posture is recomputed. The audit lands in `CLOSED`, which is terminal.

Forfeiture is not the end of the road. A `ProducerRep` may re-post a `FORFEITED` bond under the same sufficiency rule as an initial post — the `amount_cents` must be at least `amount_required_cents`, else `ERR_BOND_AMOUNT_INSUFFICIENT` — returning it to `POSTED` with the posted total and held amount recomputed. The re-post then runs the company reinstatement check: if no bond of any of the company's productions remains `FORFEITED` or `UNDERFUNDED`, the company moves from `SUSPENDED` back to `SIGNATORY`. The production's posture is recomputed as well.

### 3.8. Force Majeure, Suspension, and Closing the Production

Strikes and disasters suspend productions without erasing their history. A `UnionRep` or `ProducerRep` declares an event with `production_id`, an `event_type` of `STRIKE`, `NATURAL_DISASTER`, or `OTHER`, a `start_date` (inclusive), and an optional `end_date` that acts as an exclusive bound — a null `end_date` means the event is open-ended until lifted. Declaration requires the production to be `STAFFING` or `IN_PRODUCTION` (`ERR_PRODUCTION_STATE` otherwise). On success the production moves to `SUSPENDED`, its immediately prior status is recorded in `pre_suspension_status`, and its posture recomputes to `FROZEN` for as long as any event remains `ACTIVE`.

One production's events may not overlap. The new event's interval — running from its `start_date` up to but not including its `end_date`, or indefinitely when `end_date` is null — must not intersect any existing event of the same production, `ACTIVE` or `LIFTED`, where each existing event's effective end is its `end_date` if set, else its `lifted_date`. Adjacency is allowed: a new event whose start date equals another event's effective end does not overlap it. A genuine intersection is rejected with `ERR_FM_OVERLAP` (HTTP 409). A declared event starts `ACTIVE`.

Lifting belongs to the `UnionRep`. An `ACTIVE` event moves to `LIFTED` — lifting from any other state is `ERR_FM_STATE` — with `lifted_date` stamped from the logical clock. If no other event of the production remains `ACTIVE`, the production returns from `SUSPENDED` to the status preserved in `pre_suspension_status` (`STAFFING` or `IN_PRODUCTION`), and `pre_suspension_status` is cleared back to null. The posture is recomputed either way, and `LIFTED` is terminal.

Wrapping up requires a clean shop. Moving the production from `IN_PRODUCTION` to `WRAPPED` requires the posture not be `FROZEN` and every crew assignment of the production to be in `WRAPPED` or `TERMINATED` — any lingering `HIRED` or `ACTIVE` assignment fails with `ERR_PRODUCTION_STATE`.

Closing is the final gate. From `WRAPPED`, and again only while not `FROZEN`, a production closes when every one of its contribution reports is `ACCEPTED`, every grievance is `CLOSED`, every audit is `CLOSED` — each condition vacuously true when no such records exist — and its bond is `POSTED` or `RELEASED`. Success moves the production to `CLOSED`, which is terminal.

With the production `CLOSED`, a `FundTrustee` may release a `POSTED` bond (any other bond state, or a production not yet `CLOSED`, is `ERR_BOND_STATE`). Release is always full: the entire `amount_held_cents` moves into `total_released_cents`, the held amount is zeroed, and the bond lands in `RELEASED`, its terminal state.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, including all state-transition actions, return `200 OK`. All endpoints except the logical-clock capability are mounted under `/union-compliance`. Readers reconstruct full request and response shapes from the narratives in §2 and §3; this table is an index, not a schema.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | PlatformAdmin |
| POST | `/union-compliance/producer-companies` | Register a production company | ProducerRep |
| GET | `/union-compliance/producer-companies/{id}` | Read one company | ProducerRep, UnionRep, FundTrustee, Arbitrator, PlatformAdmin |
| GET | `/union-compliance/producer-companies/{id}/signatory-applications` | List a company's signatory applications | ProducerRep, UnionRep, FundTrustee, Arbitrator, PlatformAdmin |
| GET | `/union-compliance/producer-companies/{id}/productions` | List a company's productions | ProducerRep, UnionRep, FundTrustee, Arbitrator, PlatformAdmin |
| POST | `/union-compliance/signatory-applications` | Create a signatory application for a company | ProducerRep |
| POST | `/union-compliance/signatory-applications/{id}/submit` | Submit an application for union review | ProducerRep |
| POST | `/union-compliance/signatory-applications/{id}/request-info` | Request more information from the applicant | UnionRep |
| POST | `/union-compliance/signatory-applications/{id}/provide-info` | Answer an information request | ProducerRep |
| POST | `/union-compliance/signatory-applications/{id}/decide` | Approve or deny an application | UnionRep |
| POST | `/union-compliance/productions` | Create a production under an agreement tier | ProducerRep |
| GET | `/union-compliance/productions/{id}` | Read one production, including posture and version | ProducerRep, UnionRep, FundTrustee, Arbitrator, PlatformAdmin |
| POST | `/union-compliance/productions/{id}/budget-revisions` | Apply an OCC-guarded budget revision | ProducerRep |
| POST | `/union-compliance/productions/{id}/start-production` | Move a staffed production into production | ProducerRep |
| POST | `/union-compliance/productions/{id}/wrap-production` | Wrap a production whose crew are all terminal | ProducerRep |
| POST | `/union-compliance/productions/{id}/close` | Close a fully settled production | ProducerRep |
| GET | `/union-compliance/productions/{id}/bonds` | List the production's bond (zero or one element) | ProducerRep, UnionRep, FundTrustee, Arbitrator, PlatformAdmin |
| GET | `/union-compliance/productions/{id}/crew-assignments` | List the production's crew assignments | ProducerRep, UnionRep, FundTrustee, Arbitrator, PlatformAdmin |
| GET | `/union-compliance/productions/{id}/grievances` | List the production's grievances | ProducerRep, UnionRep, FundTrustee, Arbitrator, PlatformAdmin |
| GET | `/union-compliance/productions/{id}/contribution-reports` | List the production's contribution reports | ProducerRep, UnionRep, FundTrustee, Arbitrator, PlatformAdmin |
| GET | `/union-compliance/productions/{id}/audits` | List the production's audits | ProducerRep, UnionRep, FundTrustee, Arbitrator, PlatformAdmin |
| GET | `/union-compliance/productions/{id}/force-majeure-events` | List the production's force majeure events | ProducerRep, UnionRep, FundTrustee, Arbitrator, PlatformAdmin |
| POST | `/union-compliance/bonds/{id}/post` | Post a pending bond, or re-post after forfeiture | ProducerRep |
| POST | `/union-compliance/bonds/{id}/top-up` | Top up an underfunded bond | ProducerRep |
| POST | `/union-compliance/bonds/{id}/release` | Release a posted bond after production close | FundTrustee |
| POST | `/union-compliance/crew-assignments` | Hire a crew member onto a production | ProducerRep |
| GET | `/union-compliance/crew-assignments/{id}` | Read one crew assignment | ProducerRep, UnionRep, FundTrustee, Arbitrator, PlatformAdmin |
| GET | `/union-compliance/crew-assignments/{id}/work-day-logs` | List an assignment's work day logs | ProducerRep, UnionRep, FundTrustee, Arbitrator, PlatformAdmin |
| GET | `/union-compliance/crew-assignments/{id}/grievances` | List grievances filed against an assignment | ProducerRep, UnionRep, FundTrustee, Arbitrator, PlatformAdmin |
| POST | `/union-compliance/crew-assignments/{id}/transition` | Transition an assignment to the named state | ProducerRep |
| POST | `/union-compliance/work-day-logs` | Record a work day for an active assignment | ProducerRep |
| POST | `/union-compliance/work-day-logs/{id}/submit` | Submit an open work day log | ProducerRep |
| POST | `/union-compliance/work-day-logs/{id}/void` | Void a work day log as a correction | ProducerRep |
| POST | `/union-compliance/grievances` | File a grievance against a production | UnionRep |
| POST | `/union-compliance/grievances/{id}/accept-intake` | Accept a grievance into investigation | UnionRep |
| POST | `/union-compliance/grievances/{id}/propose-settlement` | Propose a settlement (OCC-guarded, segregated) | UnionRep |
| POST | `/union-compliance/grievances/{id}/respond-settlement` | Accept or reject an open settlement proposal | ProducerRep |
| POST | `/union-compliance/grievances/{id}/escalate` | Escalate a grievance toward arbitration | UnionRep, ProducerRep |
| POST | `/union-compliance/grievances/{id}/decide` | Render a binding arbitration award | Arbitrator |
| POST | `/union-compliance/grievances/{id}/payments` | Pay against an agreed settlement | ProducerRep |
| POST | `/union-compliance/grievances/{id}/refunds` | Reverse part of a settlement payment | ProducerRep |
| POST | `/union-compliance/contribution-reports` | Create a contribution report for a period | ProducerRep |
| POST | `/union-compliance/contribution-reports/{id}/submit` | Submit a draft report with final dues computed | ProducerRep |
| POST | `/union-compliance/contribution-reports/{id}/review` | Accept or reject a submitted report | FundTrustee |
| POST | `/union-compliance/audits` | Open a fund audit of a production | FundTrustee |
| POST | `/union-compliance/audits/{id}/issue-findings` | Issue findings and compute the assessment | FundTrustee |
| POST | `/union-compliance/audits/{id}/payments` | Pay against an issued assessment | ProducerRep |
| POST | `/union-compliance/audits/{id}/close` | Close an audit, forfeiting on unpaid findings | FundTrustee |
| POST | `/union-compliance/force-majeure-events` | Declare a strike or force majeure event | UnionRep, ProducerRep |
| POST | `/union-compliance/force-majeure-events/{id}/lift` | Lift an active force majeure event | UnionRep |

## 5. Error Code Catalogue

Trigger conditions for each error live in the narratives of §2 and §3; this table is an index of identifiers to HTTP statuses only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_APPLICATION_STATE` | 409 Conflict |
| `ERR_PRODUCTION_STATE` | 409 Conflict |
| `ERR_POSTURE_FROZEN` | 409 Conflict |
| `ERR_POSTURE_RESTRICTED` | 409 Conflict |
| `ERR_BOND_STATE` | 409 Conflict |
| `ERR_ASSIGNMENT_STATE` | 409 Conflict |
| `ERR_WORKLOG_STATE` | 409 Conflict |
| `ERR_GRIEVANCE_STATE` | 409 Conflict |
| `ERR_REPORT_STATE` | 409 Conflict |
| `ERR_AUDIT_STATE` | 409 Conflict |
| `ERR_FM_STATE` | 409 Conflict |
| `ERR_COMPANY_NOT_SIGNATORY` | 409 Conflict |
| `ERR_MIN_STAFF_UNMET` | 422 Unprocessable Entity |
| `ERR_FILING_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_CROSS_PRODUCTION_REFERENCE` | 422 Unprocessable Entity |
| `ERR_LOG_ALREADY_REPORTED` | 409 Conflict |
| `ERR_DUPLICATE_ACTIVE_ASSIGNMENT` | 409 Conflict |
| `ERR_DUPLICATE_WORK_LOG` | 409 Conflict |
| `ERR_DUPLICATE_REPORT_PERIOD` | 409 Conflict |
| `ERR_FM_OVERLAP` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_REVIEW_ROUNDS_EXHAUSTED` | 422 Unprocessable Entity |
| `ERR_EMPTY_REPORT` | 422 Unprocessable Entity |
| `ERR_INVALID_WORKLOG_TIMES` | 422 Unprocessable Entity |
| `ERR_TIER_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_BOND_AMOUNT_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_OVERPAYMENT` | 422 Unprocessable Entity |
| `ERR_REFUND_EXCEEDS_PAID` | 422 Unprocessable Entity |

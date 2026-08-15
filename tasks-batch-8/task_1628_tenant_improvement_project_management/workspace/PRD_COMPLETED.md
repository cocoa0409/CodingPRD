# Tenant Improvement Project Management API — Product Requirements Document

## 1. Introduction

Commercial landlords routinely fund or co-fund the build-out of leased premises through a negotiated tenant improvement allowance, and the lifecycle that follows — work letter negotiation, drawing review, contractor vetting, construction scheduling, allowance drawdown, punch resolution, and occupancy certification — is where money, liability, and the rent commencement date collide. This document specifies the landlord-side Tenant Improvement Project Management API: a multi-party workflow system that tracks a build-out from an executed work letter through to the certificate of occupancy, keeping the allowance ledger, the contractor bench, and the lease's financial terms consistent at every step.

Four parties act with deliberately segregated duties. A property manager runs the building side day to day; a financially separate landlord approver signs off on change orders and disbursements; the tenant's representative negotiates, files drawings, and pays overage invoices; and each contractor's representative schedules work windows, requests draws, and clears punch items, while a building engineer provides independent verification. Because several of these actors write against the same monetary state, the system pins down precise concurrency, rounding, and compensation rules so that the allowance pool, retainage balances, and tenant overage billings are always reconstructible. All business resources are mounted under `/api`, and all temporal gates in the system read a single controllable logical clock rather than the wall clock.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` identifies the acting user and `X-User-Role` names the acting role. A request missing either header, or carrying an empty value for either, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not on the endpoint's authorized list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403). The six roles, spelled exactly as the server expects them, are:

- `PlatformAdmin` — the test-harness operator; drives the logical clock and nothing else.
- `LandlordPM` — the property manager; registers the portfolio, runs lease activation, project phase advancement, work letter execution, plan review, engagement management, disbursement payment, punch logging, and invoice administration.
- `LandlordApprover` — the landlord's financial approver, segregated from PM duties; approves, rejects, and voids change orders and disbursement requests.
- `TenantRep` — the tenant's authorized representative; counters and accepts work letters, files drawing sets, submits tenant-side change orders, and pays or disputes overage invoices.
- `ContractorRep` — a contractor company's representative; acknowledges building rules, schedules and completes work windows, submits contractor-side change orders, requests draws, files lien waivers, and works punch items.
- `BuildingEngineer` — the building's technical inspector; logs and independently verifies punch items.

Role identity is interpreted in two ways. When `X-User-Role` is `TenantRep`, `X-User-ID` is the `id` of the acting `Tenant`; ownership checks on any resource reached through a lease compare the lease's `tenant_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_SCOPE` (HTTP 403). When `X-User-Role` is `ContractorRep`, `X-User-ID` is the `id` of the acting `Contractor`; ownership checks compare the targeted engagement's `contractor_id` — or the waiving contractor on a lien waiver — to `X-User-ID`, with mismatches likewise rejected as `ERR_FORBIDDEN_SCOPE`. When `X-User-Role` is `LandlordPM`, `LandlordApprover`, `BuildingEngineer`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — most notably stamping it into `approved_by_user_id` when a `LandlordApprover` approves a change order or a draw, where it later drives segregation-of-duties checks — but it never compares the value to an entity's `id`. On the `Tenant` resource itself, and on a tenant's lease list, the ownership comparison is against the tenant's own `id`. On the two list endpoints whose result sets would otherwise mix several contractors' records — the engagement list of a project and the lien-waiver list of a draw — a `ContractorRep` simply receives only its own records: the server filters the result set instead of rejecting the request.

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

List endpoints accept two query parameters. `limit` bounds the page size: it defaults to 10, must be at least 1, and may not exceed 100. `offset` selects the starting position within the full result set and defaults to 0, and must be at least 0. A `limit` or `offset` that is non-integer or falls outside these bounds is rejected with `ERR_INVALID_REQUEST` (HTTP 400). List responses sort by `created_at` ascending — oldest first — unless a more specific ordering is stated for a particular computation. The `meta` object of a list response carries `limit`, `offset`, `total_count` (the full unpaginated count of matching resources), and `has_more` (whether further pages exist beyond the returned window).

### 2.4. Resource Identity, Timestamps, and Version Tracking

Every resource in the system carries the same four server-managed properties. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps rendered with three fractional digits; `created_at` is fixed at creation while `updated_at` refreshes on every mutation. `version` is an integer that increments by exactly one on every mutation of the resource, and several workflows below also bump the `version` of a parent resource when a child's mutation changes derived parent state — those parent bumps are called out explicitly where they occur.

Beyond the common properties, several child collections assign a sequential number per parent: a work letter's `version_no`, a plan submission's `revision_no`, a change order's `co_number`, a draw's `draw_number`, and an invoice's `invoice_number` each start at 1 within their project and are assigned in `created_at` order. These numbers are never reused, even when a sibling record is withdrawn, superseded, rejected, or voided.

### 2.5. The Logical Clock

All temporal reasoning in the system — insurance expiry, disbursement period eligibility, construction-window completion, milestone completion, invoice dating — reads a single server-side logical clock, never the wall clock. Before any clock-setting call has been made, the logical clock reads exactly 2026-08-01T00:00:00Z as a fixed startup default. A `PlatformAdmin` may advance or set the clock through the clock-setting capability (`POST /_clock/set_current_utc`), supplying the target instant as `to_iso8601`; the response echoes the new reading as `current_utc`. Workflow narratives below phrase every temporal gate as a comparison against "the current logical clock", and that phrase always means this single controllable source of time. Record timestamps (`created_at`, `updated_at`) and event stamps such as a plan submission's `submitted_at` and a change order's `approved_at` are server wall-clock timestamps, not readings of the logical clock.

### 2.6. Monetary Amounts, Precision, and Rounding

Every monetary value in the system — rents, contract values, allowance pools, draw amounts, retainage, markups, invoice totals — is an integer number of cents. Request bodies that carry a non-integer or non-numeric amount are malformed and rejected with `ERR_INVALID_REQUEST` (HTTP 400). Where a calculation multiplies a cent amount by a percentage — the change-order markup, the retainage withholding, the daily rent derivation — the product is rounded half up to the nearest whole cent, and each calculation below pins the exact step at which that rounding occurs, because rounding per line and then summing can differ by a cent from rounding the sum. Day counts and window arithmetic use whole days or whole timestamps exactly as each rule states; no calculation ever produces fractional cents.

### 2.7. Request Screening and Validation Order

Inbound requests pass through a fixed screening funnel, and when several checks could fail at once the earlier stage's error is the one returned. The stages, in evaluation order, are:

1. **Authentication.** `X-User-Role` and `X-User-ID` must be present and non-empty, else `ERR_UNAUTHENTICATED` (401).
2. **Role authorization.** The role must appear in the endpoint's authorized list, else `ERR_UNAUTHORIZED_ROLE` (403).
3. **Existence.** Every resource id named in the URL path must exist, validated left to right from the outermost resource inward, else `ERR_NOT_FOUND` (404). Ids referenced inside a request body — a lease's `space_id` and `tenant_id`, an engagement's or a lien waiver's `contractor_id`, a punch item's `assigned_engagement_id` — are validated only after body well-formedness, and a missing referent is likewise `ERR_NOT_FOUND` (404).
4. **Entity-backed scope.** For the scoped `TenantRep` and `ContractorRep` endpoints, the ownership comparison of §2.1 must succeed, else `ERR_FORBIDDEN_SCOPE` (403). The check runs once the resource anchoring ownership has been loaded — after path existence and before the lifecycle and body stages — with three exceptions: work-letter counter and accept run it after the project-phase gate, change-order creation runs it after body well-formedness, and lien-waiver creation runs it after body well-formedness and the waiving contractor's existence. `ContractorRep` access to a TI project, its change orders, its disbursement requests, and its punch-item list is not engagement-scoped, and change-order submission, draw submission, and the contractor-side void of a draft draw perform no ownership check at all.
5. **Lifecycle guard.** The targeted entity must be in a state from which the requested transition exists — including the parent-phase gates named throughout §3 — and terminal states reject every transition, else `ERR_INVALID_STATE` (409). The same `ERR_INVALID_STATE` (409) also surfaces every state guard on a related entity that has no more specific error named below, including the referenced suite's `VACANT` check at lease activation, the all-milestones-terminal check at punch entry, the no-`CONFIRMED`-milestone check at engagement termination, the project-phase gates on engagement activation and completion, change-order submission, draw submission, invoice issuance, punch-item logging, verification and reopening, review-comment creation and resolution, and lien-waiver verification and rejection, the engagement-`ACTIVE` gates on milestone confirmation, `STANDARD` auto-confirmation, and punch-item start, and the terminal-ledger checks at project completion.
6. **Body well-formedness.** Required fields are present, types are correct, enum members are valid, and monetary amounts are integer cents, else `ERR_INVALID_REQUEST` (400).
7. **Business rules.** The domain checks of §3 run in their pinned per-endpoint order (see below).
8. **Concurrency guard.** Optimistic-concurrency fields are checked last, else `ERR_STALE_VERSION` (412).

Within stage 7, endpoints that enforce several business checks evaluate them in a fixed order so that the surfaced error is deterministic:

- Engagement approval checks building-rules acknowledgement first (`ERR_BUILDING_RULES_NOT_ACKNOWLEDGED`), then insurance currency (`ERR_INSURANCE_EXPIRED`), then contractor qualification (`ERR_CONTRACTOR_NOT_QUALIFIED`).
- Occupancy certificate issuance checks life-safety punch items first (`ERR_LIFE_SAFETY_ITEM_OPEN`), then the all-items check (`ERR_PUNCH_ITEMS_OPEN`) — so an open `LIFE_SAFETY` item always surfaces as the life-safety error rather than the generic one.
- Milestone scheduling checks window overlap (`ERR_SCHEDULE_OVERLAP`) before window shape (`ERR_INVALID_WINDOW`), and — for a `STANDARD` window only — checks the engagement's `ACTIVE` state (`ERR_INVALID_STATE`) after both. Milestone confirmation re-runs the overlap check, excluding the milestone itself, only after confirming the engagement is `ACTIVE` (`ERR_INVALID_STATE`).
- Starting construction checks property capacity (`ERR_PROPERTY_CONSTRUCTION_CAPACITY`), then window shape (`ERR_INVALID_WINDOW`), then the active-engagement prerequisite (`ERR_PREREQUISITE_NOT_MET`).
- Draw submission checks the work-period date (`ERR_DISBURSEMENT_PERIOD_IN_FUTURE`), then the active-engagement requirement (`ERR_NO_ACTIVE_ENGAGEMENT`), then project posture (`ERR_PROJECT_NOT_OPEN`).
- Draw approval checks, in order: a verified lien waiver exists (`ERR_LIEN_WAIVER_MISSING`); some verified waiver's amount matches the request (`ERR_LIEN_WAIVER_AMOUNT_MISMATCH`); segregation of duties (`ERR_SEGREGATION_OF_DUTIES`); project posture (`ERR_PROJECT_NOT_OPEN`); the approval does not exceed the request (`ERR_APPROVAL_EXCEEDS_REQUEST`); and the approval fits the remaining allowance (`ERR_DRAW_EXCEEDS_REMAINING`).

### 2.8. Optimistic Concurrency Control

Three write operations guard against stale reads of a parent aggregate by requiring a non-optional expected-version field in the request body; the check runs last in the screening funnel, after all business rules have passed.

- Counter-proposing a work letter (`POST /api/work-letters/{id}/counter`) requires `expected_work_letter_version` carrying the `version` of the work letter the client last observed. If the letter's current `version` has since advanced — for example because the landlord just re-proposed, advancing both `round_number` context and `version` — the counter is rejected with `ERR_STALE_VERSION` (HTTP 412), because it was drafted against a draft of the letter the tenant has not seen.
- Creating a change order against a project (`POST /api/ti-projects/{id}/change-orders`) requires `expected_ti_project_version` matching the project's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). This is the serialization point between writers of the project aggregate — a draw approval, say, that has just advanced `allowance_consumed_cents` and `version` invalidates a change order drafted against the older headroom view.
- Creating a disbursement request against a project (`POST /api/ti-projects/{id}/disbursement-requests`) likewise requires `expected_ti_project_version` matching the project's current `version`, with mismatches rejected as `ERR_STALE_VERSION` (HTTP 412) — a change-order approval that recomputed `total_cost_cents` and flipped `posture` in the interim leaves the draw writer's view of `allowance_remaining_cents` stale.

Endpoints not named here take no expected-version field at all; clients must not send one and the server does not consult `version` on those operations.

### 2.9. Hierarchical Consistency and Cascading Updates

The project aggregate is kept internally consistent by cascades that run as part of the mutation that triggers them, never asynchronously. Approving a draw recomputes the project's allowance and retainage totals and may flip its `posture`, which in turn holds or releases sibling draws; voiding an approved draw runs the same machinery in reverse. Suspending a contractor suspends every active engagement of that contractor in the same write, while reinstating the contractor deliberately does not un-suspend them. Cancelling a project runs the full compensation cascade of §3.8 across every non-terminal child — work letters, submissions, engagements, milestones, change orders, draws, and invoices all land in terminal states — and the suite returns from `UNDER_CONSTRUCTION` to `LEASED` when applicable. Every entity touched by a cascade has its own `version` incremented and `updated_at` refreshed, exactly as if it had been mutated directly.

### 2.10. Nested Resource Retrieval

Many resources are addressed through their parents — a suite within a property, a draw within a project, a waiver within a draw. Path parameters are validated left to right: the server first confirms the outermost resource exists, then the next segment, and so on inward, and the first id that does not exist aborts the request with `ERR_NOT_FOUND` (HTTP 404) before any later segment or body is examined. A child addressed under the wrong parent is, for this purpose, simply not found.

## 3. Business Logic & Workflows

### 3.1. Portfolio Setup: Properties, Suites, Tenants, and Leases

A `LandlordPM` begins by registering the building stock. Creating a property captures its display `name`, street `address`, and optionally `max_concurrent_construction_projects` — the cap on simultaneously overlapping construction windows across the whole building, which defaults to 2 when omitted and must be an integer of at least 1 when given. Suites are then created under a property; each suite records the `property_id` of its owning building together with a `suite_number` (whose uniqueness within the property the server does not enforce), an integer `floor`, and `rentable_sqft` as a strictly positive integer. A new suite's `status` starts at `VACANT`.

Tenants are registered independently of any space, with the legal entity's `legal_name`, a primary `contact_email`, and the `tax_id` used on credit documentation. A lease then binds a tenant to a suite: the creation payload names the `space_id` of the premises and the `tenant_id` of the occupant, fixes the economics through `base_rent_annual_cents` (a strictly positive integer), `scheduled_rent_commencement_date` (the contractual rent start, parsed as an ISO 8601 instant and stored rendered in UTC; a date-only value is treated as that date's UTC midnight), and `lease_term_months` (a strictly positive integer), and optionally selects the `abatement_basis` — `CALENDAR` or `BUSINESS` — that the rent-abatement computation will later use, defaulting to `CALENDAR`. A new lease is `DRAFT`, its `delay_responsibility` is `NONE`, its `rent_abatement_credit_cents` is 0, and its `actual_rent_commencement_date` stays null until an occupancy certificate is issued.

Activating a lease moves it `DRAFT` → `ACTIVE` and simultaneously flips the referenced suite `VACANT` → `LEASED`, incrementing the `version` of both records. Activation requires the referenced suite to still be `VACANT`; a suite already spoken for rejects the activation. The suite's lifecycle later continues `LEASED` → `UNDER_CONSTRUCTION` when a project's construction starts, and `UNDER_CONSTRUCTION` → `LEASED` when the occupancy certificate issues. Leases have no standalone termination endpoint: an `ACTIVE` lease moves to `TERMINATED` only as a consequence of project cancellation, at the moment the cancellation leaves every TI project of that lease in a terminal state (`COMPLETED` or `CANCELLED`).

### 3.2. Work Letter Negotiation and Allowance Establishment

A TI project is born on an `ACTIVE` lease when a `LandlordPM` supplies a `project_name` and the agreed `base_contract_cents` (an integer of zero or more); the new record carries the `lease_id` of its parent lease, starts in `INITIATED`, and all of its monetary accumulators — `allowance_total_cents`, `total_cost_cents`, `allowance_consumed_cents`, `provisional_allowance_consumed_cents`, `allowance_remaining_cents`, `overage_cents`, `retainage_held_cents`, `retainage_released_cents` — start at 0, with `posture` at `OPEN`. One lease supports at most one non-terminal project: creating a second while any project of the lease sits outside `COMPLETED` and `CANCELLED` is rejected with `ERR_ACTIVE_PROJECT_EXISTS` (HTTP 409).

Negotiation opens when the first work letter draft is created on the project — carrying a narrative `scope_description`, the `allowance_offer_cents` on the table (zero or more), and the `work_delineation` declaring who performs base-building versus suite work: `LANDLORD`, `TENANT`, or `SPLIT`. That first creation advances the project `INITIATED` → `WORK_LETTER_NEGOTIATION` and bumps the project's `version`; each draft receives a `version_no` sequential within the project and opens with its `round_number` at 0. Further drafts may be created whenever the project is in `INITIATED` or `WORK_LETTER_NEGOTIATION`; only the first creation advances the phase. Every child record the project accrues — letters, submissions, engagements, change orders, draws, punch items, invoices — carries the `project_id` of its owning project.

The negotiation cycle is a two-actor volley; tabling, countering, and accepting each require the project to still sit in `WORK_LETTER_NEGOTIATION`, while execution and withdrawal consult only the letter's own state. The landlord tables a draft, moving it `DRAFT` → `PROPOSED`, which stamps `proposed_by` as `LANDLORD`. The tenant's representative — and only the `TenantRep` whose identity matches the lease — may counter, moving `PROPOSED` → `COUNTERED` with a revised `scope_description`, `allowance_offer_cents`, and `work_delineation`; each counter increments `round_number` by exactly 1 and, because the counter is written against a specific draft, the request must carry `expected_work_letter_version` equal to the letter's current `version`, with a stale value rejected as `ERR_STALE_VERSION` per §2.8. The landlord may re-propose from `COUNTERED` back to `PROPOSED`, again stamping `proposed_by` as `LANDLORD` without touching `round_number`, and this `PROPOSED` → `COUNTERED` → `PROPOSED` volley may repeat without bound. Acceptance is likewise scoped to the owning representative: the tenant accepts a tabled letter (`PROPOSED` → `ACCEPTED`), and the landlord then executes it (`ACCEPTED` → `EXECUTED`) — execution is refused with `ERR_WORK_LETTER_ALREADY_EXECUTED` (HTTP 409) when another letter of the same project is already `EXECUTED`, because exactly one letter may ever reach that state per project. Execution is the moment the allowance pool is born: the project's `allowance_total_cents` is set from the letter's `allowance_offer_cents`, `allowance_remaining_cents` is recomputed, and both records' versions increment. At any point before acceptance the landlord may withdraw a letter from `DRAFT`, `PROPOSED`, or `COUNTERED` into `WITHDRAWN`; `EXECUTED` and `WITHDRAWN` are terminal.

### 3.3. Plan Review and Drawing Approval

With exactly one letter `EXECUTED`, the landlord moves the project `WORK_LETTER_NEGOTIATION` → `PLAN_REVIEW`; attempting the move without an executed letter is rejected with `ERR_PREREQUISITE_NOT_MET` (HTTP 422). From here the tenant drives the paper flow: the `TenantRep` owning the lease files a drawing set by supplying its external `drawing_set_ref`, and each new submission is numbered by a `revision_no` sequential within the project, is stamped with `submitted_at` set to the server's current wall-clock timestamp, starts with `review_round` at 0 and `version` at 1, and enters `SUBMITTED`. The whole filing-and-review cycle is a `PLAN_REVIEW`-phase activity: filing a set, starting a review, approving, requesting revision, and final rejection each require the project to still be in `PLAN_REVIEW`. Filing a fresh submission is also the only way out of a revision loop — when the project's prior submission sits in `REVISION_REQUIRED`, creating the next one flips the prior to `SUPERSEDED` and assigns the new record a `revision_no` one greater than its predecessor's.

The landlord picks up a submission `SUBMITTED` → `UNDER_REVIEW`, and while it is under review records review comments on it — each comment tied to its submission through `submission_id`, carrying the free-text `comment_text` and a `severity` of `INFO`, `REQUIRED`, or `BLOCKING`, and opening in `OPEN`. Comments close `OPEN` → `RESOLVED`, but only while their submission remains `UNDER_REVIEW`. Three outcomes end a review cycle. Approval moves the submission `UNDER_REVIEW` → `APPROVED` and is refused with `ERR_BLOCKING_COMMENTS_OPEN` (HTTP 422) while any comment of the submission is simultaneously `OPEN` and `BLOCKING`. Requesting revision moves it `UNDER_REVIEW` → `REVISION_REQUIRED` and increments its `review_round` by 1. Final rejection moves it `UNDER_REVIEW` → `REJECTED_FINAL`. `APPROVED`, `REJECTED_FINAL`, and `SUPERSEDED` are terminal — a superseded or finally rejected set is never reopened; the tenant simply files the next revision.

### 3.4. Contractor Qualification, Engagement, and Site Scheduling

Before any suite work begins, the project leaves design: the landlord moves the project `PLAN_REVIEW` → `PRE_CONSTRUCTION`, a step refused with `ERR_PREREQUISITE_NOT_MET` (HTTP 422) until at least one submission of the project is `APPROVED`. Staffing then runs through the contractor registry. A `LandlordPM` registers each firm with its `company_name`, `license_number`, and `insurance_expiry_date` (parsed as an ISO 8601 instant and stored rendered in UTC; a date-only value is treated as that date's UTC midnight); the firm's `qualification_status` opens at `PENDING`. Qualification moves `PENDING` → `QUALIFIED` only while the insurance expiry is strictly after the current logical clock — an expired policy surfaces `ERR_INSURANCE_EXPIRED` (HTTP 422). A qualified firm may later be suspended (`QUALIFIED` → `SUSPENDED`), which immediately cascades every `ACTIVE` engagement of that contractor into `SUSPENDED` as well; reinstatement (`SUSPENDED` → `QUALIFIED`) again requires unexpired insurance at the clock, and it pointedly does not resurrect the cascaded engagements — each one needs its own reinstatement. Revocation ends the lifecycle: from `PENDING` it is unconditional, while from `QUALIFIED` it is refused so long as any engagement of the contractor is `ACTIVE`; `REVOKED` is terminal.

Engagements attach a contractor to the project. The landlord proposes one with the `contractor_id` of the firm and a trade `scope_note`; the engagement opens `PROPOSED` with `building_rules_acknowledged` false. Proposing an engagement is not gated on the project's phase. The firm's own `ContractorRep` must first acknowledge the building rules — the acknowledge action sets `building_rules_acknowledged` true, is not gated on the engagement's status, and may be repeated, each call re-stamping the flag and bumping the record — after which the landlord's approval moves the engagement `PROPOSED` → `APPROVED` through the three-check ladder of §2.7: acknowledgement (`ERR_BUILDING_RULES_NOT_ACKNOWLEDGED`), insurance currency at the logical clock (`ERR_INSURANCE_EXPIRED`), and the firm's `QUALIFIED` standing (`ERR_CONTRACTOR_NOT_QUALIFIED`). An approved engagement becomes `ACTIVE` once the project itself is in `PRE_CONSTRUCTION` or `CONSTRUCTION`, and only `ACTIVE` engagements perform work. The landlord may suspend an `ACTIVE` engagement and later reinstate it (`SUSPENDED` → `ACTIVE`), which requires the contractor to be `QUALIFIED` at that moment, failing with `ERR_CONTRACTOR_NOT_QUALIFIED` otherwise. Termination from `PROPOSED`, `APPROVED`, or `ACTIVE` into `TERMINATED` is refused while the engagement holds any `CONFIRMED` milestone, and terminating an `ACTIVE` engagement cancels its `PLANNED` milestones in the same write. Finally, an engagement is closed out `ACTIVE` → `COMPLETED` once the project has reached `PUNCH` or `CLOSEOUT`, every one of its milestones is terminal, and every punch item assigned to it is `VERIFIED`.

Work windows are the contractor's to request: the firm's `ContractorRep` schedules a milestone on the engagement with a `milestone_name`, a `window_start`, a `window_end`, and a `work_type` of `STANDARD`, `NOISY`, `HOT_WORK`, or `FREIGHT`, with the milestone bound to its engagement through `engagement_id`. Windows are half-open — the start instant is included and the end instant excluded — and `window_end` must fall strictly after `window_start`, else `ERR_INVALID_WINDOW` (HTTP 422). Two windows on the same engagement in `PLANNED` or `CONFIRMED` may not intersect: they conflict when the existing window starts before the new window ends and the new window starts before the existing window ends, while mere adjacency — one window ending at exactly the instant the next begins — does not count as an intersection; a genuine conflict is rejected with `ERR_SCHEDULE_OVERLAP` (HTTP 409), and per §2.7 this overlap check is evaluated before the window-shape check. `COMPLETED` and `CANCELLED` milestones are ignored by the overlap computation. A `STANDARD` window is confirmed immediately at creation, transitioning straight to `CONFIRMED`; the noisier classifications stay `PLANNED` until the landlord confirms them — and confirmation, whether immediate or by the later confirm action, requires the engagement to be `ACTIVE` and the window free of overlap. Completion moves `CONFIRMED` → `COMPLETED` and is the contractor's own attestation: the acting `ContractorRep` must own the engagement, and the current logical clock must have reached or passed `window_end`, failing with `ERR_MILESTONE_WINDOW_NOT_ENDED` (HTTP 422) beforehand. The landlord may cancel a milestone from `PLANNED` or `CONFIRMED` into `CANCELLED`.

The construction phase itself begins when the landlord starts construction on the project (`PRE_CONSTRUCTION` → `CONSTRUCTION`), supplying the planned `construction_start_date` and `construction_end_date` — a closed window, inclusive of both dates, unlike the half-open milestone windows. Three gates apply in the §2.7 order. First, building capacity: the server counts the project's siblings — other TI projects on the same property, reached through their leases' spaces, currently in `CONSTRUCTION` — whose closed windows intersect the requested one, where two closed windows intersect when the sibling's start falls on or before the requested end and the requested start falls on or before the sibling's end; if that count already equals or exceeds the property's `max_concurrent_construction_projects`, the start is rejected with `ERR_PROPERTY_CONSTRUCTION_CAPACITY` (HTTP 409), and the start is permitted only while the conflict count stays strictly below the cap. Second, window shape: `construction_end_date` must fall strictly after `construction_start_date`, else `ERR_INVALID_WINDOW`. Third, staffing: at least one engagement of the project must be `ACTIVE`, else `ERR_PREREQUISITE_NOT_MET`. A successful start stamps both dates onto the project and flips the suite `LEASED` → `UNDER_CONSTRUCTION`.

### 3.5. Change Orders and Project Cost Accounting

Once the project is staffed, scope changes enter as change orders. Either the contractor's representative or the tenant's representative may draft one — supplying a `description`, a `lines` array, and `expected_ti_project_version` per the concurrency contract of §2.8 — and the draft is numbered by a `co_number` sequential within the project. Creation is not gated on the project's phase; the draft opens with its computed fields (`total_cost_cents`, `markup_cents`, `total_with_markup_cents`, `tenant_overage_share_cents`) at 0 and `submitted_by`, `approved_by_user_id`, and `approved_at` null. Each entry of `lines` pairs a line `description` with a strictly positive integer `amount_cents`; the array must contain at least one line, and an empty array is malformed and rejected with `ERR_INVALID_REQUEST`. Creating the draft already advances the project's `version`, since the project aggregate now includes the new record. A draft moves `DRAFT` → `SUBMITTED` when any `ContractorRep` or `TenantRep` files it — submission performs no ownership check — stamping `submitted_by` as `CONTRACTOR` for a `ContractorRep` or `TENANT` for a `TenantRep`; submission requires the project to be in `PRE_CONSTRUCTION`, `CONSTRUCTION`, or `PUNCH` and its `posture` to be `OPEN` — a project in `ON_HOLD` or `ALLOWANCE_EXHAUSTED` posture rejects the submission with `ERR_PROJECT_NOT_OPEN` (HTTP 422).

Approval belongs to the `LandlordApprover` alone, applies while the project is in `PRE_CONSTRUCTION`, `CONSTRUCTION`, or `PUNCH`, and triggers the project's core cost computation. First the markup runs over the order's own lines: each line's markup is ten percent of its `amount_cents`, rounded half up to a whole cent per line, and only then summed — the order's `total_cost_cents` is the plain sum of its line amounts, its `markup_cents` is the sum of those per-line-rounded markups, and its `total_with_markup_cents` is the two added together; the per-line-first rounding order is normative, since rounding the aggregate instead can produce a different cent. Immediately afterward the tenant-funded share is swept in chronological order. The headroom is the project's `allowance_total_cents` minus its `base_contract_cents`. The server walks the project's other `APPROVED` change orders in approval order — `approved_at` ascending, ties broken by `created_at` ascending — accumulating their `total_with_markup_cents` into a running cumulative total; the new order's `tenant_overage_share_cents` is then the excess of the cumulative total including this order over the headroom (floored at zero) minus the excess of the cumulative total excluding this order over the headroom (likewise floored at zero). Change orders in `DRAFT`, `SUBMITTED`, `REJECTED`, or `VOIDED` never participate in the sweep. Approval stamps `approved_by_user_id` with the approver's `X-User-ID` and `approved_at` with the server's current wall-clock timestamp — the ordering key the sweep relies on — and recomputes the project's `total_cost_cents` as `base_contract_cents` plus the `total_with_markup_cents` of every `APPROVED` change order, its `overage_cents` as the amount by which `total_cost_cents` exceeds `allowance_total_cents` (never below zero), and its `posture` per §3.6, bumping the project's `version`.

Rejection moves `SUBMITTED` → `REJECTED` with no financial effect. Voiding moves `APPROVED` → `VOIDED` and runs exact compensation: the order's `total_with_markup_cents` is subtracted back out of the project's `total_cost_cents`, `overage_cents` is recomputed, and the posture recomputation may release held draws — so approving and then voiding an order leaves the project's total cost exactly as it found it. The void is refused with `ERR_INVOICE_ALREADY_ISSUED` (HTTP 422) once the order is included in an overage invoice that has been issued through the manual issue action or paid, unless that invoice has since been voided; an invoice auto-issued by the occupancy-certificate cascade of §3.7 does not block the void unless it is subsequently paid, and a `DRAFT` invoice never blocks it. The server tracks this issued-or-paid bookkeeping as a flag on the change-order record itself, and the flag appears in the record's response representation once set. `REJECTED` and `VOIDED` are terminal.

### 3.6. Allowance Disbursement, Retainage, and Lien Waivers

The project tracks its allowance through two consumption lenses. The final variant, `allowance_consumed_cents`, sums `approved_amount_cents` across the project's draws in `APPROVED` or `PAID` and nothing else; the provisional variant, `provisional_allowance_consumed_cents`, adds on the full `requested_amount_cents` of draws still waiting in `SUBMITTED` or `ON_HOLD`, so the provisional figure is always at least the final one while review is pending — and it is a read-side preview only, never an input to gating. `allowance_remaining_cents` is `allowance_total_cents` minus `allowance_consumed_cents`. Both variants refresh whenever a draw enters or leaves `SUBMITTED`, `ON_HOLD`, `APPROVED`, `PAID`, `REJECTED`, or `VOIDED`, and when a work letter is executed. The refreshes triggered by a draw's submission or rejection update the project's derived fields without advancing the project's `version`; the project's `version` advances on draw-draft creation, approval, payment, and the approver-side void.

The project's `posture` is derived from the final variant: it is `ALLOWANCE_EXHAUSTED` when the pool is funded (a total above zero) and consumption has reached or passed it — consumption exactly equal to the pool already exhausts it; otherwise it is `ON_HOLD` when any draw of the project sits in `ON_HOLD`; otherwise it is `OPEN`. Posture flips are themselves cascades: entering `ALLOWANCE_EXHAUSTED` moves every `SUBMITTED` draw of the project to `ON_HOLD`, and leaving it back to `OPEN` returns every `ON_HOLD` draw to `SUBMITTED`. That exit is direct: a posture recomputation that finds consumption back below the pool settles the posture at `OPEN` — never `ON_HOLD` — and releases the held draws in the same recomputation, since a draw reaches `ON_HOLD` only as a product of the exhaustion cascade.

A draw begins when the contractor's representative creates the request with the `period_end_date` closing the work period it covers, the gross `requested_amount_cents` (strictly positive), and an optional `is_final_draw` flag defaulting to false; creation also carries `expected_ti_project_version` per §2.8 and assigns a `draw_number` sequential within the project. Creation is gated neither on the project's phase nor on any engagement-ownership check; like a change-order draft, it advances the project's `version`, and the draft opens with `approved_amount_cents`, `retainage_held_cents`, and `net_payment_cents` at 0 and `approved_by_user_id` null. Submission moves `DRAFT` → `SUBMITTED` through the ordered gates of §2.7: the project must be in `CONSTRUCTION` or `PUNCH`; `period_end_date` must not lie after the current logical clock, else `ERR_DISBURSEMENT_PERIOD_IN_FUTURE` (HTTP 422); at least one engagement of the project must be `ACTIVE`, else `ERR_NO_ACTIVE_ENGAGEMENT` (HTTP 422); and `posture` must be `OPEN`, else `ERR_PROJECT_NOT_OPEN`.

Lien protection rides on each draw. The `ContractorRep` attaches waivers to the request — each naming its draw through `disbursement_id`, identifying the waiving firm by `contractor_id`, declaring a `waiver_type` of `CONDITIONAL_PROGRESS`, `UNCONDITIONAL_PROGRESS`, `CONDITIONAL_FINAL`, or `UNCONDITIONAL_FINAL`, and covering a strictly positive `amount_cents` — and each waiver opens `PENDING`. Attachment is not gated on the draw's state. The landlord verifies or rejects waivers (`PENDING` → `VERIFIED`, or `PENDING` → `REJECTED`) only while the underlying draw is `SUBMITTED` or `ON_HOLD`; both outcomes are terminal for the waiver.

Approval of a draw is the most heavily guarded write in the system. The `LandlordApprover` supplies `approved_amount_cents` (an integer of zero or more), and §2.7's ladder runs in order: at least one waiver on the draw must be `VERIFIED`, else `ERR_LIEN_WAIVER_MISSING` (HTTP 422); at least one verified waiver's `amount_cents` must equal the draw's `requested_amount_cents`, else `ERR_LIEN_WAIVER_AMOUNT_MISMATCH`; the approver's `X-User-ID` must differ from the `approved_by_user_id` stamped on every `APPROVED` change order of the same project, else `ERR_SEGREGATION_OF_DUTIES` (HTTP 422); the project's `posture` must be `OPEN`, else `ERR_PROJECT_NOT_OPEN`; the approved amount may not exceed `requested_amount_cents`, else `ERR_APPROVAL_EXCEEDS_REQUEST` (HTTP 422); and it may not exceed the project's `allowance_remaining_cents`, else `ERR_DRAW_EXCEEDS_REMAINING` (HTTP 422) — an approval exactly equal to the remaining allowance is permitted. A successful approval stamps the draw's own `approved_by_user_id` and runs retainage. The withholding percentage depends on how much of the allowance was already spoken for before this draw: the server sums `approved_amount_cents` over the project's other draws in `APPROVED` or `PAID`, and if that prior cumulative total is below half of `allowance_total_cents` the early rate of ten percent applies, while a cumulative total equal to or above that half-way threshold drops the rate to five percent; the draw's `retainage_held_cents` is its `approved_amount_cents` times the applicable rate, rounded half up to a whole cent, and its `net_payment_cents` is the approved amount minus that withholding. A draw marked `is_final_draw` withholds nothing at approval — its retainage is zero by definition. The approval then adds `approved_amount_cents` into the project's `allowance_consumed_cents`, adds the draw's withholding into the project's `retainage_held_cents`, recomputes the remaining and provisional figures, and re-evaluates `posture` — which may cascade sibling `SUBMITTED` draws onto `ON_HOLD` as described above.

Payment moves `APPROVED` → `PAID` under the `LandlordPM`. For an ordinary draw the paid-out amount is simply its `net_payment_cents`. Paying the final draw releases everything still held: the project's entire `retainage_held_cents` balance is added into `retainage_released_cents`, the held balance is zeroed, and the final payout is the draw's `net_payment_cents` plus that released retainage. The release runs through to the draws that fed the escrow: in the same payment, every draw of the project still `APPROVED` or `PAID` has its own `retainage_held_cents` zeroed, so the project's held balance remains the sum of the surviving per-draw withholdings; only the paid draw and the project advance their `version` in this operation. Rejection moves `SUBMITTED` → `REJECTED`, refreshing the provisional consumption and the posture. Voiding has two flavors: the contractor may void a `DRAFT` draw outright, while voiding an `APPROVED` draw is the approver's compensation path — the draw's `approved_amount_cents` comes back out of `allowance_consumed_cents`, its withholding comes back out of the project's `retainage_held_cents`, the remaining allowance is recomputed, and the posture re-evaluation may return `ON_HOLD` draws to `SUBMITTED`. `PAID`, `REJECTED`, and `VOIDED` are terminal.

### 3.7. Punch List, Occupancy Certification, and Rent Abatement

Construction winds down in two controlled steps. The landlord opens the punch phase (`CONSTRUCTION` → `PUNCH`) only once the current logical clock has reached or passed the project's `construction_end_date` — earlier attempts fail with `ERR_CONSTRUCTION_WINDOW_NOT_ENDED` (HTTP 422) — and only once every milestone on every engagement of the project has reached a terminal state, `COMPLETED` or `CANCELLED`. In the punch phase, deficiencies are logged by the `LandlordPM` or the `BuildingEngineer`, each item bound to the project and to the responsible crew through `assigned_engagement_id`, with a free-text `description`, a suite `location` note, and a `severity` of `COSMETIC`, `STANDARD`, or `LIFE_SAFETY`; items open in `OPEN`. The named engagement is validated only for existence — it need not belong to the project, nor be `ACTIVE`, when the item is logged.

Clearing an item is a handshake between the trades and the building. The responsible firm's `ContractorRep` starts work (`OPEN` → `IN_PROGRESS`) — permitted only while the assigned engagement is `ACTIVE` — and later marks the fix done (`IN_PROGRESS` → `RESOLVED`). Verification belongs to the `BuildingEngineer` alone and requires the project to be in `PUNCH`: a passed inspection moves `RESOLVED` → `VERIFIED`, the item's terminal state, while a failed one reopens the item (`RESOLVED` → `OPEN`), sending it back around the `IN_PROGRESS` → `RESOLVED` loop again.

Issuing the occupancy certificate closes the build: the landlord supplies the municipal `occupancy_certificate_ref`, the certificate's `issued_on` date, and the `delay_responsibility` declaration — `NONE`, `LANDLORD`, or `TENANT` — and the project moves `PUNCH` → `CLOSEOUT`. The gate is the punch list, checked in the §2.7 order: any `LIFE_SAFETY` item not yet `VERIFIED` blocks issuance with `ERR_LIFE_SAFETY_ITEM_OPEN` (HTTP 422), and once those are clear, any remaining item of any severity not `VERIFIED` blocks it with `ERR_PUNCH_ITEMS_OPEN` (HTTP 422). On issuance the project stamps its `substantial_completion_date` from `issued_on` alongside the certificate reference, the suite returns `UNDER_CONSTRUCTION` → `LEASED`, and every `DRAFT` overage invoice of the project is issued automatically — its `invoice_number` unchanged and its due date computed from the certificate's `issued_on` per §3.8.

Certificate issuance is also the moment the lease's rent terms settle. The lease's `delay_responsibility` is stamped from the payload, and the abatement computation runs. The daily rent is the lease's `base_rent_annual_cents` divided by 365, rounded half up to a whole cent. The delay period opens the day after `scheduled_rent_commencement_date` and closes on `substantial_completion_date`, inclusive of the closing date; when substantial completion falls on or before the scheduled date there is no delay at all and the delay count is zero. Under the `CALENDAR` basis the delay count is every date in that period; under the `BUSINESS` basis only dates falling on a Monday through Friday count, so a period spanning a weekend yields a strictly smaller count. When responsibility is `LANDLORD`, the lease's `rent_abatement_credit_cents` becomes the delay count times the daily rent and its `actual_rent_commencement_date` becomes `substantial_completion_date`. When responsibility is `TENANT` — the tenant caused the delay — the credit is zero and rent still commences on `scheduled_rent_commencement_date`; the same zero-credit, on-schedule outcome applies when responsibility is `NONE`, the on-time delivery case.

### 3.8. Overage Invoicing, Closeout, and Cancellation

Tenant-funded overage is billed through invoices drafted by the `LandlordPM`. Drafting an invoice snapshots the outstanding share: the server sums `tenant_overage_share_cents` across the project's `APPROVED` change orders that carry a share above zero and have not yet been included in any non-`VOID` invoice, and that sum becomes the invoice's `line_total_cents`, frozen at creation; the invoice takes the next `invoice_number` in the project and opens in `DRAFT` with `due_date` still null. Drafting is not gated on the project's phase. When nothing qualifies — no uninvoiced approved order with a positive share — the draft is refused with `ERR_NO_OVERAGE_OUTSTANDING` (HTTP 422).

An invoice may be issued manually while the project is in `CONSTRUCTION`, `PUNCH`, or `CLOSEOUT`, moving `DRAFT` → `ISSUED` and setting `due_date` to thirty days after the current logical-clock reading; invoices issued through the certificate cascade of §3.7 instead take their effective issue date from the certificate's `issued_on`, so their `due_date` falls thirty days after substantial completion. The owning `TenantRep` settles an issued invoice in full (`ISSUED` → `PAID`) or contests it (`ISSUED` → `DISPUTED`), and the landlord may reissue a disputed invoice (`DISPUTED` → `ISSUED`) — the dispute loop may repeat as often as needed, and reissuing does not change the `due_date`. The landlord may also void an invoice from `DRAFT` or `ISSUED` into `VOID`; voiding releases the invoice's included change orders, which thereafter qualify for drafting into a new invoice again and no longer trigger the `ERR_INVOICE_ALREADY_ISSUED` block of §3.5. `PAID` and `VOID` are terminal.

Final completion moves the project `CLOSEOUT` → `COMPLETED` and demands a clean ledger: every draw of the project must sit in `PAID`, `REJECTED`, or `VOIDED`; every invoice in `PAID` or `VOID`; and every engagement in `TERMINATED` or `COMPLETED`. `COMPLETED` and `CANCELLED` are the project's terminal states.

Cancellation is the system's great compensating transaction, and the landlord may invoke it from any non-terminal project state, with the cascade widening as the project matures. From `INITIATED` there are no children to compensate. From `WORK_LETTER_NEGOTIATION`, every work letter in `DRAFT`, `PROPOSED`, `COUNTERED`, or `ACCEPTED` is moved to `WITHDRAWN`. From `PLAN_REVIEW` the same letter cascade applies, and every plan submission in `SUBMITTED`, `UNDER_REVIEW`, or `REVISION_REQUIRED` is moved to `REJECTED_FINAL`. From `PRE_CONSTRUCTION` the letter and submission cascades apply, every engagement in `PROPOSED` or `APPROVED` moves to `TERMINATED`, and every change order in `DRAFT` or `SUBMITTED` is `REJECTED` while any `APPROVED` order is `VOIDED` with its cost backed out of `total_cost_cents` exactly as in §3.5. From `CONSTRUCTION` the full cascade runs: letters and submissions as above; every engagement in `PROPOSED`, `APPROVED`, `ACTIVE`, or `SUSPENDED` is `TERMINATED`; every milestone in `PLANNED` or `CONFIRMED` is `CANCELLED`; change orders are rejected or voided with compensation as above; every draw in `DRAFT`, `SUBMITTED`, or `ON_HOLD` is `VOIDED`, and any `APPROVED` draw is `VOIDED` with its consumption and retainage backed out of the project exactly as in §3.6; every invoice in `DRAFT`, `ISSUED`, or `DISPUTED` is moved to `VOID`; and the suite, if it stands `UNDER_CONSTRUCTION` for this project, returns to `LEASED`. From `PUNCH` the same compensation cascade as from `CONSTRUCTION` applies, with punch items simply left as they stand — `VERIFIED` items are already terminal and the rest drop from consideration — and the suite likewise returns to `LEASED`. From `CLOSEOUT` the same compensation cascade as from `CONSTRUCTION` applies. Throughout every variant, each entity touched by the cascade takes its own `version` increment, and the project's `version` increments as well. And as §3.1 records, when a cancellation leaves every project of the parent lease in a terminal state, the lease itself moves `ACTIVE` → `TERMINATED`.

## 4. Endpoint Definitions

All endpoints share the envelope of §2.2 and the screening funnel of §2.7. Creating a new resource returns HTTP 201 with the created record; reads, state transitions, and other modifications return HTTP 200 with the affected record (or page of records). Request payloads, derived-field behavior, and cascades are specified in §3; the table below is only an index.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Set the server's logical clock (startup default 2026-08-01T00:00:00Z) | PlatformAdmin |
| POST | /api/properties | Create a building | LandlordPM |
| GET | /api/properties/{id} | Fetch a property | LandlordPM, LandlordApprover, BuildingEngineer |
| POST | /api/properties/{id}/lease-spaces | Create a suite in a property | LandlordPM |
| GET | /api/properties/{id}/lease-spaces | List suites of a property | LandlordPM, LandlordApprover, BuildingEngineer |
| GET | /api/lease-spaces/{id} | Fetch a suite | LandlordPM, LandlordApprover, BuildingEngineer |
| GET | /api/lease-spaces/{id}/leases | List leases on a suite | LandlordPM, LandlordApprover |
| POST | /api/tenants | Register a tenant | LandlordPM |
| GET | /api/tenants/{id} | Fetch a tenant | LandlordPM, LandlordApprover, TenantRep |
| GET | /api/tenants/{id}/leases | List leases of a tenant | LandlordPM, LandlordApprover, TenantRep |
| POST | /api/leases | Create a lease in `DRAFT` | LandlordPM |
| GET | /api/leases/{id} | Fetch a lease | LandlordPM, LandlordApprover, TenantRep |
| POST | /api/leases/{id}/activate | Activate a `DRAFT` lease; flips its space `VACANT` → `LEASED` | LandlordPM |
| GET | /api/leases/{id}/ti-projects | List TI projects of a lease | LandlordPM, LandlordApprover, TenantRep |
| POST | /api/contractors | Register a contractor (`PENDING`) | LandlordPM |
| GET | /api/contractors/{id} | Fetch a contractor | LandlordPM, LandlordApprover, ContractorRep |
| POST | /api/contractors/{id}/qualify | `PENDING` → `QUALIFIED` (insurance must be unexpired) | LandlordPM |
| POST | /api/contractors/{id}/suspend | `QUALIFIED` → `SUSPENDED`; cascades to `ACTIVE` engagements | LandlordPM |
| POST | /api/contractors/{id}/reinstate | `SUSPENDED` → `QUALIFIED` | LandlordPM |
| POST | /api/contractors/{id}/revoke | `PENDING` or `QUALIFIED` → `REVOKED` (blocked while any engagement is `ACTIVE`) | LandlordPM |
| GET | /api/contractors/{id}/contractor-engagements | List engagements of a contractor | LandlordPM, LandlordApprover, ContractorRep |
| GET | /api/contractors/{id}/lien-waivers | List lien waivers filed by a contractor | LandlordPM, LandlordApprover, ContractorRep |
| POST | /api/leases/{id}/ti-projects | Create a TI project (`INITIATED`) on an `ACTIVE` lease | LandlordPM |
| GET | /api/ti-projects/{id} | Fetch a project with all computed monetary fields | LandlordPM, LandlordApprover, TenantRep, ContractorRep, BuildingEngineer |
| POST | /api/ti-projects/{id}/begin-plan-review | `WORK_LETTER_NEGOTIATION` → `PLAN_REVIEW` (requires `EXECUTED` work letter) | LandlordPM |
| POST | /api/ti-projects/{id}/begin-pre-construction | `PLAN_REVIEW` → `PRE_CONSTRUCTION` (requires `APPROVED` plan) | LandlordPM |
| POST | /api/ti-projects/{id}/start-construction | `PRE_CONSTRUCTION` → `CONSTRUCTION`; sets window; capacity check; space → `UNDER_CONSTRUCTION` | LandlordPM |
| POST | /api/ti-projects/{id}/begin-punch | `CONSTRUCTION` → `PUNCH` (clock past `construction_end_date`; milestones terminal) | LandlordPM |
| POST | /api/ti-projects/{id}/issue-occupancy-certificate | `PUNCH` → `CLOSEOUT`; sets substantial completion; runs rent abatement; auto-issues `DRAFT` invoices; space → `LEASED` | LandlordPM |
| POST | /api/ti-projects/{id}/complete | `CLOSEOUT` → `COMPLETED` (all draws, invoices, engagements terminal) | LandlordPM |
| POST | /api/ti-projects/{id}/cancel | Any non-terminal state → `CANCELLED` with full compensation cascade | LandlordPM |
| POST | /api/ti-projects/{id}/work-letters | Create a work letter draft (first creation advances project `INITIATED` → `WORK_LETTER_NEGOTIATION`) | LandlordPM |
| GET | /api/ti-projects/{id}/work-letters | List work letters of a project | LandlordPM, LandlordApprover, TenantRep |
| GET | /api/work-letters/{id} | Fetch a work letter | LandlordPM, LandlordApprover, TenantRep |
| POST | /api/work-letters/{id}/propose | `DRAFT` or `COUNTERED` → `PROPOSED` (landlord tables a draft) | LandlordPM |
| POST | /api/work-letters/{id}/counter | `PROPOSED` → `COUNTERED` (tenant counters; OCC on the letter's `version`) | TenantRep |
| POST | /api/work-letters/{id}/accept | `PROPOSED` → `ACCEPTED` (tenant accepts) | TenantRep |
| POST | /api/work-letters/{id}/execute | `ACCEPTED` → `EXECUTED`; stamps the project's allowance pool | LandlordPM |
| POST | /api/work-letters/{id}/withdraw | `DRAFT`, `PROPOSED`, or `COUNTERED` → `WITHDRAWN` | LandlordPM |
| POST | /api/ti-projects/{id}/plan-submissions | Tenant files a drawing set; supersedes the prior `REVISION_REQUIRED` submission | TenantRep |
| GET | /api/ti-projects/{id}/plan-submissions | List plan submissions of a project | LandlordPM, LandlordApprover, TenantRep |
| GET | /api/plan-submissions/{id} | Fetch a plan submission | LandlordPM, LandlordApprover, TenantRep |
| POST | /api/plan-submissions/{id}/start-review | `SUBMITTED` → `UNDER_REVIEW` | LandlordPM |
| POST | /api/plan-submissions/{id}/approve | `UNDER_REVIEW` → `APPROVED` (blocked by open `BLOCKING` comments) | LandlordPM |
| POST | /api/plan-submissions/{id}/request-revision | `UNDER_REVIEW` → `REVISION_REQUIRED`; `review_round` increments | LandlordPM |
| POST | /api/plan-submissions/{id}/reject-final | `UNDER_REVIEW` → `REJECTED_FINAL` | LandlordPM |
| POST | /api/plan-submissions/{id}/comments | Add a review comment to a submission under review | LandlordPM |
| GET | /api/plan-submissions/{id}/comments | List comments on a submission | LandlordPM, LandlordApprover, TenantRep |
| GET | /api/plan-review-comments/{id} | Fetch a review comment | LandlordPM, LandlordApprover, TenantRep |
| POST | /api/plan-review-comments/{id}/resolve | `OPEN` → `RESOLVED` | LandlordPM |
| POST | /api/ti-projects/{id}/contractor-engagements | Propose an engagement (`PROPOSED`) | LandlordPM |
| GET | /api/ti-projects/{id}/contractor-engagements | List engagements of a project | LandlordPM, LandlordApprover, TenantRep, ContractorRep |
| GET | /api/contractor-engagements/{id} | Fetch an engagement | LandlordPM, LandlordApprover, ContractorRep |
| POST | /api/contractor-engagements/{id}/acknowledge-rules | Contractor acknowledges building rules | ContractorRep |
| POST | /api/contractor-engagements/{id}/approve | `PROPOSED` → `APPROVED` (rules acknowledged, insurance current, contractor qualified) | LandlordPM |
| POST | /api/contractor-engagements/{id}/activate | `APPROVED` → `ACTIVE` (project in `PRE_CONSTRUCTION` or `CONSTRUCTION`) | LandlordPM |
| POST | /api/contractor-engagements/{id}/suspend | `ACTIVE` → `SUSPENDED` | LandlordPM |
| POST | /api/contractor-engagements/{id}/reinstate | `SUSPENDED` → `ACTIVE` (contractor `QUALIFIED`) | LandlordPM |
| POST | /api/contractor-engagements/{id}/terminate | `PROPOSED`, `APPROVED`, or `ACTIVE` → `TERMINATED` (no `CONFIRMED` milestones; `PLANNED` cascade-cancel) | LandlordPM |
| POST | /api/contractor-engagements/{id}/complete | `ACTIVE` → `COMPLETED` (project in `PUNCH`/`CLOSEOUT`; milestones terminal; assigned punch `VERIFIED`) | LandlordPM |
| POST | /api/contractor-engagements/{id}/milestones | Schedule a work window (`STANDARD` auto-confirms; others stay `PLANNED`); half-open overlap check | ContractorRep |
| GET | /api/contractor-engagements/{id}/milestones | List milestones of an engagement | LandlordPM, LandlordApprover, ContractorRep, BuildingEngineer |
| GET | /api/schedule-milestones/{id} | Fetch a milestone | LandlordPM, LandlordApprover, ContractorRep, BuildingEngineer |
| POST | /api/schedule-milestones/{id}/confirm | `PLANNED` → `CONFIRMED` | LandlordPM |
| POST | /api/schedule-milestones/{id}/complete | `CONFIRMED` → `COMPLETED` (clock past `window_end`; contractor-owned) | ContractorRep |
| POST | /api/schedule-milestones/{id}/cancel | `PLANNED` or `CONFIRMED` → `CANCELLED` | LandlordPM |
| POST | /api/ti-projects/{id}/change-orders | Create a change order draft (OCC on the project's `version`) | ContractorRep, TenantRep |
| GET | /api/ti-projects/{id}/change-orders | List change orders of a project | LandlordPM, LandlordApprover, TenantRep, ContractorRep |
| GET | /api/change-orders/{id} | Fetch a change order | LandlordPM, LandlordApprover, TenantRep, ContractorRep |
| POST | /api/change-orders/{id}/submit | `DRAFT` → `SUBMITTED` | ContractorRep, TenantRep |
| POST | /api/change-orders/{id}/approve | `SUBMITTED` → `APPROVED`; markup, overage-share sweep, project cost and posture cascade | LandlordApprover |
| POST | /api/change-orders/{id}/reject | `SUBMITTED` → `REJECTED` | LandlordApprover |
| POST | /api/change-orders/{id}/void | `APPROVED` → `VOIDED` with compensation (blocked once invoiced) | LandlordApprover |
| POST | /api/ti-projects/{id}/disbursement-requests | Create a draw draft (OCC on the project's `version`) | ContractorRep |
| GET | /api/ti-projects/{id}/disbursement-requests | List draws of a project | LandlordPM, LandlordApprover, TenantRep, ContractorRep |
| GET | /api/disbursement-requests/{id} | Fetch a draw | LandlordPM, LandlordApprover, TenantRep, ContractorRep |
| POST | /api/disbursement-requests/{id}/submit | `DRAFT` → `SUBMITTED` (temporal, engagement, and posture gates) | ContractorRep |
| POST | /api/disbursement-requests/{id}/approve | `SUBMITTED` → `APPROVED`; retainage, allowance consumption, segregation-of-duties, lien-waiver gate | LandlordApprover |
| POST | /api/disbursement-requests/{id}/pay | `APPROVED` → `PAID`; the final draw releases held retainage | LandlordPM |
| POST | /api/disbursement-requests/{id}/reject | `SUBMITTED` → `REJECTED` | LandlordApprover |
| POST | /api/disbursement-requests/{id}/void | `DRAFT` or `APPROVED` → `VOIDED`; approved-void compensates allowance and retainage | ContractorRep, LandlordApprover |
| POST | /api/disbursement-requests/{id}/lien-waivers | Attach a lien waiver to a draw | ContractorRep |
| GET | /api/disbursement-requests/{id}/lien-waivers | List waivers on a draw | LandlordPM, LandlordApprover, TenantRep, ContractorRep |
| GET | /api/lien-waivers/{id} | Fetch a lien waiver | LandlordPM, LandlordApprover, ContractorRep |
| POST | /api/lien-waivers/{id}/verify | `PENDING` → `VERIFIED` | LandlordPM |
| POST | /api/lien-waivers/{id}/reject | `PENDING` → `REJECTED` | LandlordPM |
| POST | /api/ti-projects/{id}/punch-items | Log a punch item (project in `PUNCH`) | LandlordPM, BuildingEngineer |
| GET | /api/ti-projects/{id}/punch-items | List punch items of a project | LandlordPM, LandlordApprover, TenantRep, ContractorRep, BuildingEngineer |
| GET | /api/contractor-engagements/{id}/punch-items | List punch items assigned to an engagement | LandlordPM, LandlordApprover, ContractorRep, BuildingEngineer |
| GET | /api/punch-items/{id} | Fetch a punch item | LandlordPM, LandlordApprover, ContractorRep, BuildingEngineer |
| POST | /api/punch-items/{id}/start | `OPEN` → `IN_PROGRESS` | ContractorRep |
| POST | /api/punch-items/{id}/resolve | `IN_PROGRESS` → `RESOLVED` | ContractorRep |
| POST | /api/punch-items/{id}/verify | `RESOLVED` → `VERIFIED` | BuildingEngineer |
| POST | /api/punch-items/{id}/reopen | `RESOLVED` → `OPEN` (failed verification) | BuildingEngineer |
| POST | /api/ti-projects/{id}/overage-invoices | Draft an invoice over uninvoiced `APPROVED` change orders with positive tenant share | LandlordPM |
| GET | /api/ti-projects/{id}/overage-invoices | List invoices of a project | LandlordPM, LandlordApprover, TenantRep |
| GET | /api/overage-invoices/{id} | Fetch an invoice | LandlordPM, LandlordApprover, TenantRep |
| POST | /api/overage-invoices/{id}/issue | `DRAFT` → `ISSUED`; sets `due_date` thirty days out | LandlordPM |
| POST | /api/overage-invoices/{id}/pay | `ISSUED` → `PAID` (tenant pays in full) | TenantRep |
| POST | /api/overage-invoices/{id}/dispute | `ISSUED` → `DISPUTED` (tenant disputes) | TenantRep |
| POST | /api/overage-invoices/{id}/reissue | `DISPUTED` → `ISSUED` | LandlordPM |
| POST | /api/overage-invoices/{id}/void | `DRAFT` or `ISSUED` → `VOID` | LandlordPM |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows that raise them in §2 and §3; this table is only an index of identifiers to HTTP status codes.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_FORBIDDEN_SCOPE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_BUILDING_RULES_NOT_ACKNOWLEDGED | 422 |
| ERR_INSURANCE_EXPIRED | 422 |
| ERR_LIFE_SAFETY_ITEM_OPEN | 422 |
| ERR_PUNCH_ITEMS_OPEN | 422 |
| ERR_BLOCKING_COMMENTS_OPEN | 422 |
| ERR_SCHEDULE_OVERLAP | 409 |
| ERR_PROPERTY_CONSTRUCTION_CAPACITY | 409 |
| ERR_ACTIVE_PROJECT_EXISTS | 409 |
| ERR_WORK_LETTER_ALREADY_EXECUTED | 409 |
| ERR_INVALID_WINDOW | 422 |
| ERR_DISBURSEMENT_PERIOD_IN_FUTURE | 422 |
| ERR_CONSTRUCTION_WINDOW_NOT_ENDED | 422 |
| ERR_MILESTONE_WINDOW_NOT_ENDED | 422 |
| ERR_CONTRACTOR_NOT_QUALIFIED | 422 |
| ERR_NO_ACTIVE_ENGAGEMENT | 422 |
| ERR_PREREQUISITE_NOT_MET | 422 |
| ERR_LIEN_WAIVER_MISSING | 422 |
| ERR_LIEN_WAIVER_AMOUNT_MISMATCH | 422 |
| ERR_SEGREGATION_OF_DUTIES | 422 |
| ERR_PROJECT_NOT_OPEN | 422 |
| ERR_APPROVAL_EXCEEDS_REQUEST | 422 |
| ERR_DRAW_EXCEEDS_REMAINING | 422 |
| ERR_NO_OVERAGE_OUTSTANDING | 422 |
| ERR_INVOICE_ALREADY_ISSUED | 422 |
